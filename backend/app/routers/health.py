from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(request: Request) -> HealthResponse:
    db = request.app.state.db
    llm_service = request.app.state.llm_service

    try:
        db_ok = db.check_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        )

    keys_configured = len(llm_service.keys)
    if keys_configured < 1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no LLM keys configured",
        )

    return HealthResponse(
        status="ok",
        keys_configured=keys_configured,
        cache_enabled=llm_service.cache_enabled,
    )
