from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ProviderKeyConfig:
    """Represents a single configured provider API key without exposing it in logs."""

    key_id: str
    api_key: str
    model: str


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_ENV), str(_BACKEND_ENV)),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_keys_raw: str = Field(default="", alias="LLM_API_KEYS")
    llm_model: str = Field(default="gemini/gemini-2.0-flash", alias="LLM_MODEL")
    llm_models_raw: str = Field(default="", alias="LLM_MODELS")
    default_system_prompt: Optional[str] = Field(default=None, alias="DEFAULT_SYSTEM_PROMPT")
    database_url: str = Field(default="sqlite:///./data/app.db", alias="DATABASE_URL")
    allowed_origins_raw: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="ALLOWED_ORIGINS",
    )
    enable_failure_simulation: bool = Field(default=False, alias="ENABLE_FAILURE_SIMULATION")
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_type: str = Field(default="local", alias="CACHE_TYPE")
    request_timeout_seconds: float = Field(default=45.0, alias="LLM_TIMEOUT_SECONDS")

    @property
    def provider_keys(self) -> list[ProviderKeyConfig]:
        keys = [k.strip() for k in self.llm_api_keys_raw.split(",") if k.strip()]
        models = [m.strip() for m in self.llm_models_raw.split(",") if m.strip()]
        pool: list[ProviderKeyConfig] = []
        for idx, api_key in enumerate(keys):
            model = models[idx] if idx < len(models) else self.llm_model
            pool.append(
                ProviderKeyConfig(
                    key_id=f"key_{idx + 1}",
                    api_key=api_key,
                    model=model,
                )
            )
        return pool

    @property
    def allowed_origins(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.allowed_origins_raw.split(",") if o.strip()]
        return origins or ["http://localhost:3000"]

    @property
    def sqlite_path(self) -> str:
        url = self.database_url.strip()
        if url == "sqlite:///:memory:":
            return ":memory:"
        if url.startswith("sqlite:////"):
            # Four slashes: absolute POSIX path like sqlite:////data/app.db -> /data/app.db
            path_part = "/" + url[len("sqlite:////") :]
        elif url.startswith("sqlite:///"):
            path_part = url[len("sqlite:///") :]
        else:
            path_part = url
        return str(Path(path_part)) if path_part != ":memory:" else ":memory:"
