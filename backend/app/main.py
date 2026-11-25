from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings
from app.database import Database
from app.routers import chat, health, sessions
from app.services.litellm_service import LiteLLMService

logger = logging.getLogger("lyftr.app")


def create_app(custom_settings: Optional[Settings] = None) -> FastAPI:
    settings = custom_settings or Settings()
    db = Database(settings.sqlite_path)
    llm_service = LiteLLMService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db()
        yield
        db.close()

    app = FastAPI(
        title="Lyftr AI LLM Chatbot API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.db = db
    app.state.llm_service = llm_service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "loc": err.get("loc", []),
                "msg": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled server error on %s: %s", request.url.path, type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "internal server error"},
        )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)

    return app


app = create_app()
