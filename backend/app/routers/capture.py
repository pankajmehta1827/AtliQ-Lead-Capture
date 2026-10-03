from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serializers as ser
from ..db import get_db
from ..deps import current_user
from ..models import SourceItem
from ..parsing import parse_markdown_item
from ..services.capture import enqueue_item, process_pending
from ..services.seed import ingest_sample_dataset

router = APIRouter(prefix="/api/capture", tags=["capture"])


class ManualCapture(BaseModel):
    channel: Literal["email", "meeting", "linkedin"] = "email"
    text: str = Field(min_length=10, max_length=50_000)
    subject: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    occurred_at: date | None = None


@router.post("")
def capture_manual(body: ManualCapture, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """Paste an email thread, meeting notes, or a LinkedIn conversation shared by the user (FR-12: one-click
    share, no scraping)."""
    parsed = parse_markdown_item(body.text, None, body.channel)
    if body.subject:
        parsed["subject"] = body.subject
        parsed["title"] = body.subject
    if body.contact_email:
        parsed["participants"] = [{"name": body.contact_name, "email": body.contact_email.lower()}, *parsed["participants"]]
        parsed["sender_email"] = parsed["sender_email"] or body.contact_email.lower()
        parsed["sender_name"] = parsed["sender_name"] or body.contact_name
    if body.occurred_at:
        parsed["occurred_at"] = body.occurred_at
    parsed["occurred_at"] = parsed["occurred_at"] or date.today()
    digest = hashlib.sha256(body.text.encode()).hexdigest()[:16]
    parsed["external_ref"] = f"manual/{body.channel}/{digest}"
    item, created = enqueue_item(db, parsed, user)
    return {"item": ser.source_item(item), "created": created}


@router.post("/upload")
async def capture_upload(
    files: list[UploadFile] = File(...), user: str = Depends(current_user), db: Session = Depends(get_db)
):
    results = []
    for f in files[:50]:
        raw = (await f.read())[:200_000].decode("utf-8", errors="replace")
        channel = "meeting" if "meeting" in (f.filename or "").lower() else None
        parsed = parse_markdown_item(raw, f"upload/{f.filename}", channel)
        item, created = enqueue_item(db, parsed, user)
        results.append({"file": f.filename, "item_id": item.id, "created": created})
    return {"results": results}


@router.post("/sample")
def capture_sample(limit: int | None = None, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """Simulated mailbox + calendar sync using the bundled AtliQ dataset."""
    return ingest_sample_dataset(db, user, limit)


@router.post("/process")
def process_now(limit: int = 10, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """Process queued items synchronously (the background worker does this automatically)."""
    return process_pending(db, limit=min(limit, 50))


@router.get("/items")
def list_items(status: str | None = None, limit: int = 200, db: Session = Depends(get_db), _: str = Depends(current_user)):
    q = select(SourceItem).order_by(SourceItem.id.desc()).limit(min(limit, 500))
    if status:
        q = q.where(SourceItem.status == status)
    counts = dict(db.execute(select(SourceItem.status, func.count()).group_by(SourceItem.status)).all())
    return {"items": [ser.source_item(i) for i in db.scalars(q).all()], "counts": counts}


@router.post("/items/{item_id}/retry")
def retry_item(item_id: int, user: str = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(SourceItem, item_id)
    if not item:
        raise HTTPException(404)
    if item.status != "failed":
        raise HTTPException(409, "Only failed items can be retried")
    item.status, item.attempts = "queued", 0
    db.commit()
    return ser.source_item(item)
