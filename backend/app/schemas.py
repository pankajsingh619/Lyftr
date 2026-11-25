from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    session_id: str
    message: str
    system_prompt: Optional[str] = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed or len(value) > 128:
            raise ValueError("session_id must be between 1 and 128 characters")
        return trimmed

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed or len(trimmed) > 4000:
            raise ValueError("message must be between 1 and 4000 characters after trimming")
        return trimmed

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if len(trimmed) > 16000:
            raise ValueError("system_prompt must be at most 16000 characters")
        return trimmed


class ChatMetadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    key_id: Optional[str]
    fallback_attempts: int = Field(ge=0)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class UserMessageOut(BaseModel):
    role: Literal["user"] = "user"
    content: str


class AssistantMessageOut(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    metadata: dict[str, Any]


class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: list[Union[UserMessageOut, AssistantMessageOut]]
