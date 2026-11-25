from __future__ import annotations

from typing import Optional

import litellm

SIMULATABLE_STATUSES = {429, 500, 502, 503}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def parse_simulate_failure_header(raw_header: Optional[str]) -> dict[str, int]:
    """Parse X-Simulate-Failure header (e.g. 'key_1=429,key_2=500' or '*=429')."""
    if not raw_header:
        return {}
    parsed: dict[str, int] = {}
    for entry in raw_header.split(","):
        item = entry.strip()
        if not item or "=" not in item:
            continue
        key_part, status_part = item.split("=", 1)
        key_id = key_part.strip()
        try:
            status_code = int(status_part.strip())
        except ValueError:
            continue
        if key_id and status_code in SIMULATABLE_STATUSES:
            parsed[key_id] = status_code
    return parsed


def build_simulated_exception(status_code: int, key_id: str, model: str) -> Exception:
    """Create a request-scoped LiteLLM exception matching the requested HTTP status."""
    provider = model.split("/", 1)[0] if "/" in model else "custom"
    message = f"Simulated provider failure HTTP {status_code} for {key_id}"
    if status_code == 429:
        return litellm.RateLimitError(message=message, llm_provider=provider, model=model)
    if status_code == 500:
        return litellm.InternalServerError(message=message, llm_provider=provider, model=model)
    if status_code == 503:
        return litellm.ServiceUnavailableError(message=message, llm_provider=provider, model=model)
    return litellm.APIError(
        status_code=status_code,
        message=message,
        llm_provider=provider,
        model=model,
    )


def is_retryable_exception(exc: Exception) -> bool:
    """Return True for transient, rate-limit, quota, or 5xx errors that warrant failover."""
    if isinstance(exc, (litellm.BadRequestError, litellm.AuthenticationError)):
        return False

    retryable_types = [
        litellm.RateLimitError,
        litellm.ServiceUnavailableError,
        litellm.InternalServerError,
        litellm.Timeout,
        litellm.APIConnectionError,
    ]
    bad_gateway_cls = getattr(litellm, "BadGatewayError", None)
    if bad_gateway_cls is not None:
        retryable_types.append(bad_gateway_cls)

    if isinstance(exc, tuple(retryable_types)):
        return True

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code in RETRYABLE_STATUS_CODES:
        return True

    lowered = str(exc).lower()
    quota_markers = ("429", "rate limit", "rate_limit", "quota", "resource_exhausted", "overloaded")
    return any(marker in lowered for marker in quota_markers)
