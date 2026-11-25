from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas import AssistantMessageOut, SessionMessagesResponse, UserMessageOut

router = APIRouter()


@router.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
def get_session_messages(session_id: str, request: Request) -> SessionMessagesResponse:
    db = request.app.state.db
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )

    stored_messages = db.get_messages(session_id)
    items: list[UserMessageOut | AssistantMessageOut] = []
    for msg in stored_messages:
        if msg.role == "user":
            items.append(UserMessageOut(content=msg.content))
        else:
            items.append(
                AssistantMessageOut(
                    content=msg.content,
                    metadata=msg.metadata or {},
                )
            )

    return SessionMessagesResponse(
        session_id=session_id,
        messages=items,
    )
