from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import serializers as ser
from ..audit import log_action
from ..catalogue import STAGES
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import CrossSellSuggestion, Deal, DealActivity, Draft, Reminder
from ..services.pipeline_health import daily_summary, scan_reminders

router = APIRouter(prefix="/api", tags=["pipeline"])

_FLAG_WEIGHT = {"proposal_unanswered": 5, "followup_overdue": 4, "inactive": 3, "no_next_step": 2, "no_owner": 1, "no_status": 1}


@router.get("/deals")
def list_deals(owner: str | None = None, open_only: bool = True, db: Session = Depends(get_db), _: str = Depends(current_user)):
    q = select(Deal).options(joinedload(Deal.company), joinedload(Deal.contact))
    if owner:
        q = q.where(Deal.owner == owner)
    deals = [ser.deal(d) for d in db.scalars(q).unique().all()]
    if open_only:
        deals = [d for d in deals if d["is_open"]]
    # FR-7 / user story: flagged deals at the top, biggest first.
    deals.sort(key=lambda d: (-sum(_FLAG_WEIGHT.get(f, 0) for f in d["flags"]), -(d["est_value_usd"] or 0)))
    return deals


@router.get("/deals/{deal_id}")
def get_deal(deal_id: int, db: Session = Depends(get_db), _: str = Depends(current_user)):
    d = db.get(Deal, deal_id)
    if not d:
        raise HTTPException(404)
    acts = db.scalars(
        select(DealActivity).options(joinedload(DealActivity.source_item))
        .where(DealActivity.deal_id == deal_id).order_by(DealActivity.created_at.desc())
    ).unique().all()
    rems = db.scalars(select(Reminder).where(Reminder.deal_id == deal_id).order_by(Reminder.due_date)).all()
    ideas = db.scalars(select(CrossSellSuggestion).where(CrossSellSuggestion.deal_id == deal_id)).all()
    pending = db.scalars(select(Draft).where(Draft.deal_id == deal_id, Draft.status == "pending")).all()
    return {
        "deal": ser.deal(d),
        "activities": [
            {"id": a.id, "occurred_at": a.occurred_at and a.occurred_at.isoformat(), "summary": a.summary,
             "changes": a.changes, "actor": a.actor, "source": ser.source_item(a.source_item)}
            for a in acts
        ],
        "reminders": [ser.reminder(r) for r in rems],
        "crosssell": [ser.crosssell(c) for c in ideas],
        "pending_drafts": [p.id for p in pending],
    }


class DealPatch(BaseModel):
    status: str | None = None
    owner: str | None = None
    next_step: str | None = None
    next_followup_date: date | None = None
    est_value_usd: float | None = None
    service_interest: str | None = None
    source: str | None = None
    requirement: str | None = None
    notes: str | None = None


@router.patch("/deals/{deal_id}")
def patch_deal(deal_id: int, body: DealPatch, user: str = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(Deal, deal_id)
    if not d:
        raise HTTPException(404)
    if body.status and body.status not in STAGES:
        raise HTTPException(422, f"status must be one of {STAGES}")
    changes = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        old = getattr(d, k)
        if v != old:
            changes[k] = {"from": str(old) if old is not None else None, "to": str(v) if v is not None else None}
            setattr(d, k, v)
    if changes:
        db.add(DealActivity(deal_id=d.id, summary="Manual edit", changes=changes, actor=user))
        log_action(db, actor=user, action="deal_edited", outcome="ok", entity_type="deal", entity_id=d.id,
                   details={"changes": changes})
    db.commit()
    return ser.deal(d)


# ---------------------------------------------------------------- reminders

@router.get("/reminders")
def list_reminders(
    status: str = "open", owner: str | None = None, due_only: bool = False,
    db: Session = Depends(get_db), _: str = Depends(current_user),
):
    q = (
        select(Reminder).options(joinedload(Reminder.deal).joinedload(Deal.company), joinedload(Reminder.deal).joinedload(Deal.contact), joinedload(Reminder.source_item))
        .where(Reminder.status == status).order_by(Reminder.due_date)
    )
    if owner:
        q = q.where(Reminder.owner == owner)
    if due_only:
        q = q.where(Reminder.due_date <= get_settings().today())
    return [ser.reminder(r) for r in db.scalars(q).unique().all()]


@router.post("/reminders/scan")
def run_scan(_: str = Depends(current_user), db: Session = Depends(get_db)):
    return {"created": scan_reminders(db)}


class ReminderAction(BaseModel):
    action: Literal["done", "dismiss", "snooze"]
    days: int = 3


@router.post("/reminders/{reminder_id}")
def act_on_reminder(reminder_id: int, body: ReminderAction, user: str = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Reminder, reminder_id)
    if not r:
        raise HTTPException(404)
    if body.action == "snooze":
        r.due_date = max(r.due_date, get_settings().today()) + timedelta(days=max(1, min(body.days, 90)))
    else:
        r.status = "done" if body.action == "done" else "dismissed"
        r.resolved_at = datetime.now(timezone.utc)
    log_action(db, actor=user, action=f"reminder_{body.action}", outcome="ok", entity_type="reminder",
               entity_id=r.id, details={"deal_id": r.deal_id, "due_date": r.due_date.isoformat()})
    db.commit()
    return ser.reminder(r)


# ---------------------------------------------------------------- cross-sell, summary

@router.get("/crosssell")
def list_crosssell(status: str = "open", db: Session = Depends(get_db), _: str = Depends(current_user)):
    q = select(CrossSellSuggestion).options(joinedload(CrossSellSuggestion.deal).joinedload(Deal.company)).where(
        CrossSellSuggestion.status == status)
    return [ser.crosssell(c) for c in db.scalars(q).unique().all()]


class StatusBody(BaseModel):
    status: Literal["open", "accepted", "dismissed"]


@router.post("/crosssell/{idea_id}")
def set_crosssell_status(idea_id: int, body: StatusBody, user: str = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(CrossSellSuggestion, idea_id)
    if not c:
        raise HTTPException(404)
    c.status = body.status
    log_action(db, actor=user, action="crosssell_" + body.status, outcome="ok", entity_type="crosssell", entity_id=c.id)
    db.commit()
    return ser.crosssell(c)


@router.get("/summary/daily")
def get_daily_summary(owner: str | None = None, db: Session = Depends(get_db), _: str = Depends(current_user)):
    return daily_summary(db, owner)
