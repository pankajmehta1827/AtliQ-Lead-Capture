from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import serializers as ser
from ..db import get_db
from ..deps import current_user
from ..models import Draft
from ..services.review import confirm_draft, discard_draft

router = APIRouter(prefix="/api/drafts", tags=["review queue"])


class ConfirmBody(BaseModel):
    edits: dict[str, Any] = {}
    target_deal_id: int | None = None
    create_new: bool = False


class DiscardBody(BaseModel):
    reason: str | None = None


@router.get("")
def list_drafts(
    status: str = "pending", owner: str | None = None, db: Session = Depends(get_db), _: str = Depends(current_user)
):
    q = (
        select(Draft).options(joinedload(Draft.source_item), joinedload(Draft.deal))
        .where(Draft.status == status).order_by(Draft.needs_review, Draft.created_at.desc())
    )
    if owner:
        q = q.where(Draft.owner == owner)
    return [ser.draft(d) for d in db.scalars(q).unique().all()]


def _get(db: Session, draft_id: int) -> Draft:
    d = db.get(Draft, draft_id)
    if not d:
        raise HTTPException(404, "Draft not found")
    return d


@router.get("/{draft_id}")
def get_draft(draft_id: int, db: Session = Depends(get_db), _: str = Depends(current_user)):
    return ser.draft(_get(db, draft_id), with_source=True)


@router.post("/{draft_id}/preview")
def preview(draft_id: int, body: ConfirmBody, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """What Confirm would change in the CRM, computed by a rolled-back dry run. Nothing is saved or logged."""
    return confirm_draft(db, _get(db, draft_id), user, body.edits, body.target_deal_id, body.create_new, dry_run=True)


@router.post("/{draft_id}/confirm")
def confirm(draft_id: int, body: ConfirmBody, user: str = Depends(current_user), db: Session = Depends(get_db)):
    deal = confirm_draft(db, _get(db, draft_id), user, body.edits, body.target_deal_id, body.create_new)
    return {"deal": ser.deal(deal)}


@router.post("/{draft_id}/discard")
def discard(draft_id: int, body: DiscardBody, user: str = Depends(current_user), db: Session = Depends(get_db)):
    discard_draft(db, _get(db, draft_id), user, body.reason)
    return {"ok": True}
