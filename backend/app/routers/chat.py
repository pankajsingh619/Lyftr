from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.schemas import ChatMetadata, ChatRequest, ChatResponse
from app.services.litellm_service import AllProvidersUnavailableError, ProviderClientError

router = APIRouter()


class _SessionLockManager:
    """Reference-counted per-session locks to serialize concurrent writes on the same session."""

    def __init__(self) -> None:
        self._guard = Lock()
        self._locks: dict[str, list] = {}  # session_id -> [Lock, ref_count]

    @contextmanager
    def acquire(self, session_id: str) -> Iterator[None]:
        with self._guard:
            entry = self._locks.get(session_id)
            if entry is None:
                entry = [Lock(), 0]
                self._locks[session_id] = entry
            entry[1] += 1
            session_lock: Lock = entry[0]

        session_lock.acquire()
        try:
            yield
        finally:
            session_lock.release()
            with self._guard:
                entry[1] -= 1
                if entry[1] <= 0:
                    self._locks.pop(session_id, None)


_session_locks = _SessionLockManager()


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    x_simulate_failure: str | None = Header(default=None, alias="X-Simulate-Failure"),
) -> ChatResponse:
    db = request.app.state.db
    llm_service = request.app.state.llm_service
    settings = request.app.state.settings

    with _session_locks.acquire(payload.session_id):
        existing_session = db.get_session(payload.session_id)
        effective_system_prompt = (
            payload.system_prompt
            if payload.system_prompt is not None
            else (
                existing_session.system_prompt
                if existing_session is not None and existing_session.system_prompt is not None
                else (settings.default_system_prompt.strip() if settings.default_system_prompt else None)
            )
        )
        if effective_system_prompt == "":
            effective_system_prompt = None

        history = db.get_messages(payload.session_id)

        litellm_messages: list[dict[str, str]] = []
        if effective_system_prompt:
            litellm_messages.append({"role": "system", "content": effective_system_prompt})
        for msg in history:
            litellm_messages.append({"role": msg.role, "content": msg.content})
        litellm_messages.append({"role": "user", "content": payload.message})

        try:
            result = llm_service.complete_chat(
                messages=litellm_messages,
                simulate_failure_header=x_simulate_failure,
            )
        except AllProvidersUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="all providers unavailable",
            ) from exc
        except ProviderClientError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc

        metadata = ChatMetadata(
            resolution_source=result.resolution_source,
            model=result.model,
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            key_id=result.key_id,
            fallback_attempts=result.fallback_attempts,
        )

        db.save_turn(
            session_id=payload.session_id,
            system_prompt=effective_system_prompt,
            user_content=payload.message,
            assistant_content=result.reply,
            assistant_metadata=metadata.model_dump(),
        )

    return ChatResponse(
        session_id=payload.session_id,
        reply=result.reply,
        metadata=metadata,
    )
