from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import litellm

from app.config import ProviderKeyConfig, Settings
from app.services.cache_service import CacheService
from app.services.failover_service import (
    build_simulated_exception,
    is_retryable_exception,
    parse_simulate_failure_header,
)

logger = logging.getLogger("lyftr.litellm")


class AllProvidersUnavailableError(Exception):
    """Raised when every configured provider key fails with a transient/quota error."""


class ProviderClientError(Exception):
    """Raised for non-retryable client or authentication errors (e.g. 400/401)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class CompletionResult:
    reply: str
    resolution_source: str  # "LIVE_INFERENCE" or "LLM_CACHE"
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: Optional[str]
    fallback_attempts: int


def _extract_reply_text(response: Any) -> str:
    if response is None:
        return ""
    choices = getattr(response, "choices", None)
    if not choices and isinstance(response, dict):
        choices = response.get("choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        content = "\n".join(parts)
    if not isinstance(content, str):
        return ""
    return content.strip()


def _extract_token_usage(
    response: Any,
    model: str,
    messages: list[dict[str, str]],
    reply_text: str,
) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    if usage is not None:
        if isinstance(usage, dict):
            raw_in = usage.get("prompt_tokens", usage.get("input_tokens"))
            raw_out = usage.get("completion_tokens", usage.get("output_tokens"))
        else:
            raw_in = getattr(usage, "prompt_tokens", None)
            if raw_in is None:
                raw_in = getattr(usage, "input_tokens", None)
            raw_out = getattr(usage, "completion_tokens", None)
            if raw_out is None:
                raw_out = getattr(usage, "output_tokens", None)

        if isinstance(raw_in, (int, float)) and raw_in >= 0:
            input_tokens = int(raw_in)
        if isinstance(raw_out, (int, float)) and raw_out >= 0:
            output_tokens = int(raw_out)

    # Reliable tokenizer fallback only when provider omits usage fields
    if input_tokens is None:
        try:
            input_tokens = int(litellm.token_counter(model=model, messages=messages))
        except Exception:
            input_tokens = max(1, sum(len(m.get("content", "").split()) for m in messages))

    if output_tokens is None:
        try:
            output_tokens = int(litellm.token_counter(model=model, text=reply_text))
        except Exception:
            output_tokens = max(1, len(reply_text.split())) if reply_text else 0

    return input_tokens, output_tokens


class LiteLLMService:
    """Gateway around LiteLLM coordinating key pool failover, caching, and token tracking."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.keys: list[ProviderKeyConfig] = settings.provider_keys
        self.cache_service = CacheService(
            enabled=settings.cache_enabled,
            cache_type=settings.cache_type,
        )

    @property
    def cache_enabled(self) -> bool:
        return self.cache_service.enabled

    def clear_cache(self) -> None:
        self.cache_service.clear()

    def complete_chat(
        self,
        messages: list[dict[str, str]],
        simulate_failure_header: Optional[str] = None,
    ) -> CompletionResult:
        if not self.keys:
            raise AllProvidersUnavailableError("No LLM API keys configured")

        start = time.perf_counter()

        simulated_failures: dict[str, int] = {}
        if self.settings.enable_failure_simulation:
            simulated_failures = parse_simulate_failure_header(simulate_failure_header)

        # Simulated failures must never be masked by an existing cache entry.
        bypass_cache = bool(simulated_failures)
        fallback_attempts = 0

        for key_cfg in self.keys:
            simulated_status = simulated_failures.get(key_cfg.key_id) or simulated_failures.get("*")
            try:
                if simulated_status is not None:
                    raise build_simulated_exception(simulated_status, key_cfg.key_id, key_cfg.model)

                completion_kwargs: dict[str, Any] = {
                    "model": key_cfg.model,
                    "messages": messages,
                    "api_key": key_cfg.api_key,
                    "timeout": self.settings.request_timeout_seconds,
                    "num_retries": 0,
                    **self.cache_service.build_completion_cache_kwargs(bypass_cache),
                }

                response = litellm.completion(**completion_kwargs)
                reply_text = _extract_reply_text(response)
                if not reply_text:
                    # Prevent empty/malformed responses from poisoning LiteLLM's cache across retries.
                    self.cache_service.evict(model=key_cfg.model, messages=messages)
                    raise litellm.ServiceUnavailableError(
                        message="Provider returned an empty response",
                        llm_provider=key_cfg.model.split("/", 1)[0],
                        model=key_cfg.model,
                    )

                latency_ms = max(0, int(round((time.perf_counter() - start) * 1000)))
                cache_hit = (
                    (not bypass_cache)
                    and self.cache_enabled
                    and self.cache_service.is_cache_hit(response)
                )

                response_model = getattr(response, "model", None) or key_cfg.model
                model_name = key_cfg.model if "/" in key_cfg.model else str(response_model)
                input_tokens, output_tokens = _extract_token_usage(
                    response=response,
                    model=key_cfg.model,
                    messages=messages,
                    reply_text=reply_text,
                )

                if cache_hit:
                    return CompletionResult(
                        reply=reply_text,
                        resolution_source="LLM_CACHE",
                        model=model_name,
                        latency_ms=latency_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        key_id=None,
                        fallback_attempts=0,
                    )

                return CompletionResult(
                    reply=reply_text,
                    resolution_source="LIVE_INFERENCE",
                    model=model_name,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    key_id=key_cfg.key_id,
                    fallback_attempts=fallback_attempts,
                )

            except Exception as exc:
                if is_retryable_exception(exc):
                    fallback_attempts += 1
                    logger.warning(
                        "Provider call failed for %s (%s); failing over",
                        key_cfg.key_id,
                        type(exc).__name__,
                    )
                    continue

                status_code = getattr(exc, "status_code", 400)
                if not isinstance(status_code, int) or status_code < 400 or status_code >= 500:
                    status_code = 400
                raise ProviderClientError(
                    "Invalid request or authentication failure at LLM provider",
                    status_code=status_code,
                ) from exc

        raise AllProvidersUnavailableError("all providers unavailable")
