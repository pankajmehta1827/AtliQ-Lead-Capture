from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Deal
from ..services.assist import ask_pipeline, draft_email

router = APIRouter(prefix="/api", tags=["ai assist"])


def _ai_call(fn, *args):
    """Turn provider failures into a clear message instead of a 500."""
    try:
        return fn(*args)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if type(exc).__name__ == "RateLimitError" or "rate limit" in text.lower():
            raise HTTPException(429, "The AI provider's rate limit was reached. Try again in a few minutes.") from exc
        raise HTTPException(503, f"The AI couldn't answer this time ({type(exc).__name__}). Please try again.") from exc


class EmailRequest(BaseModel):
    instructions: str = Field(default="", max_length=500)
    reminder_ids: list[int] = []


@router.post("/deals/{deal_id}/email-draft")
def email_draft(deal_id: int, body: EmailRequest, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """#4 Draft a follow-up email for the owner to edit and send themselves. Nothing is sent or saved."""
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    return _ai_call(draft_email, db, deal, user, body.instructions, body.reminder_ids)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    history: list[Turn] = []


@router.post("/ask")
def ask(body: AskRequest, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """#5 Ask your pipeline: answers from the CRM and saved conversations, with deal links and quotes."""
    return _ai_call(ask_pipeline, db, body.question, [t.model_dump() for t in body.history[-6:]], user)
