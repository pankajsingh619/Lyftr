from __future__ import annotations

import importlib
import logging
from typing import Any

import litellm
from litellm.caching.caching import Cache

logger = logging.getLogger("lyftr.cache")


class CacheService:
    """Manages LiteLLM's built-in response cache lifecycle and hit detection."""

    def __init__(self, enabled: bool, cache_type: str = "local") -> None:
        self.enabled = enabled
        self.cache_type = cache_type.lower()
        self._configure()

    def _configure(self) -> None:
        litellm.suppress_debug_info = True
        if self.enabled:
            if self.cache_type != "local":
                logger.warning("Unsupported CACHE_TYPE '%s' in LiteLLM; falling back to 'local'", self.cache_type)
            litellm.cache = Cache(type="local")
            # Preload lazy cache-hit handler modules so the first cache hit stays fast.
            try:
                importlib.import_module("litellm.llms.anthropic.messages.native.response_cache")
            except Exception:
                pass
        else:
            litellm.cache = None

    def clear(self) -> None:
        if litellm.cache is not None and hasattr(litellm.cache, "flush_cache"):
            litellm.cache.flush_cache()

    def evict(self, model: str, messages: list[dict[str, str]]) -> None:
        """Remove a specific entry (e.g. an empty provider reply) from LiteLLM cache."""
        if litellm.cache is None:
            return
        try:
            cache_key = litellm.cache.get_cache_key(model=model, messages=messages)
            backend = getattr(litellm.cache, "cache", None)
            if backend is not None and hasattr(backend, "delete_cache"):
                backend.delete_cache(cache_key)
        except Exception:
            pass

    def build_completion_cache_kwargs(self, bypass_cache: bool) -> dict[str, Any]:
        if self.enabled and not bypass_cache:
            return {"caching": True}
        return {
            "caching": False,
            "cache": {"no-cache": True, "no-store": True},
        }

    @staticmethod
    def is_cache_hit(response: Any) -> bool:
        hidden = getattr(response, "_hidden_params", None)
        if isinstance(hidden, dict) and hidden.get("cache_hit") is True:
            return True
        if isinstance(response, dict):
            hidden_dict = response.get("_hidden_params")
            if isinstance(hidden_dict, dict) and hidden_dict.get("cache_hit") is True:
                return True
        return False
