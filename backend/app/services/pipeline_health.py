"""Pipeline flags (FR-7), rule-based reminders (FR-6) and the daily summary (FR-13)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..audit import log_action
from ..config import get_settings
from ..db import SessionLocal
from ..matching import CLOSED_STATUSES
from ..models import Deal, Draft, Reminder, SourceItem

log = logging.getLogger("atliq.health")


def deal_flags(deal: Deal, today: date) -> dict[str, Any]:
    s = get_settings()
    flags: list[str] = []
    days = (today - deal.last_contact_date).days if deal.last_contact_date else None
    is_open = deal.status not in CLOSED_STATUSES
    if is_open:
        if days is None or days > s.inactive_days:
            flags.append("inactive")
        if not deal.next_step and not deal.next_followup_date:
            flags.append("no_next_step")
        if deal.status == "Proposal Sent" and (days is None or days >= s.proposal_unanswered_days):
            flags.append("proposal_unanswered")
        if deal.next_followup_date and deal.next_followup_date < today:
            flags.append("followup_overdue")
        if not deal.status:
            flags.append("no_status")
        if not deal.owner:
            flags.append("no_owner")
    return {"flags": flags, "days_since_contact": days, "is_open": is_open}


NO_NEXT_STEP_GRACE_DAYS = 2  # a dated next step should be agreed within 2 days of contact


def reminder_deadline(r: Reminder) -> date:
    """When the follow-up actually fell due, for the live timers. Rule-based reminders are created on the
    day of the scan, so their due_date is 'today'; the real clock starts when the deal went off track."""
    s = get_settings()
    deal = r.deal
    anchor = (deal.last_contact_date or deal.created_date) if deal else None
    if r.kind == "proposal_unanswered" and anchor:
        return anchor + timedelta(days=s.proposal_unanswered_days)
    if r.kind == "inactive" and anchor:
        return anchor + timedelta(days=s.inactive_days)
    if r.kind == "no_next_step" and anchor:
        return min(r.due_date, anchor + timedelta(days=NO_NEXT_STEP_GRACE_DAYS))
    return r.due_date


_KIND_BASE = {"proposal_unanswered": 62, "commitment": 58, "inactive": 48, "no_next_step": 40}


def reminder_priority(r: Reminder, today: date) -> int:
    """Transparent 0-100 ranking for the Today queue: what is at stake and how late it is.
    Not a model score: kind of signal + days overdue + deal value."""
    score = _KIND_BASE.get(r.kind, 45)
    score += min(20, max(0, (today - r.due_date).days) * 2)
    value = r.deal.est_value_usd if r.deal else None
    score += min(18, int((value or 0) / 5000))
    return max(0, min(99, score))


def _ensure_reminder(db: Session, deal: Deal, kind: str, reason: str, due: date, step: str) -> bool:
    exists = db.scalar(select(Reminder).where(Reminder.deal_id == deal.id, Reminder.kind == kind, Reminder.status == "open"))
    if exists:
        return False
    db.add(Reminder(deal_id=deal.id, kind=kind, reason=reason, due_date=due, suggested_next_step=step, owner=deal.owner))
    return True


def scan_reminders(db: Session) -> int:
    s = get_settings()
    today = s.today()
    created = 0
    deals = db.scalars(select(Deal).options(joinedload(Deal.company))).unique().all()
    for deal in deals:
        info = deal_flags(deal, today)
        if not info["is_open"]:
            continue
        name = deal.company.name if deal.company else deal.lead_code
        days = info["days_since_contact"]
        since = f"{days} days" if days is not None else "ever (no contact recorded)"
        if "proposal_unanswered" in info["flags"]:
            created += _ensure_reminder(
                db, deal, "proposal_unanswered", f"Proposal to {name} unanswered for {since}", today,
                "Chase the proposal: ask for feedback or a decision date",
            )
        elif "inactive" in info["flags"]:
            created += _ensure_reminder(
                db, deal, "inactive", f"No contact with {name} for {since}", today,
                "Re-engage the contact or update the deal status",
            )
        if "no_next_step" in info["flags"]:
            created += _ensure_reminder(
                db, deal, "no_next_step", f"{name} has no next step recorded", today,
                "Agree and record a next step with a date",
            )
        if "followup_overdue" in info["flags"] and deal.next_followup_date:
            exists = db.scalar(select(Reminder).where(
                Reminder.deal_id == deal.id, Reminder.due_date == deal.next_followup_date, Reminder.status == "open"))
            if not exists:
                db.add(Reminder(
                    deal_id=deal.id, kind="commitment", reason=f"Follow-up date reached for {name}",
                    due_date=deal.next_followup_date, suggested_next_step=deal.next_step or "Follow up", owner=deal.owner,
                ))
                created += 1
    if created:
        log_action(db, actor="assistant", action="reminder_scan", outcome="created", details={"created": created})
    db.commit()
    return created


def daily_summary(db: Session, owner: str | None = None) -> dict[str, Any]:
    today = get_settings().today()
    drafts_q = select(Draft).options(joinedload(Draft.source_item)).where(Draft.status == "pending")
    rem_q = (
        select(Reminder).options(joinedload(Reminder.deal).joinedload(Deal.company))
        .where(Reminder.status == "open", Reminder.due_date <= today)
    )
    if owner:
        drafts_q = drafts_q.where(Draft.owner == owner)
        rem_q = rem_q.where(Reminder.owner == owner)
    drafts = db.scalars(drafts_q.order_by(Draft.created_at)).unique().all()
    reminders = db.scalars(rem_q.order_by(Reminder.due_date)).unique().all()

    deals_q = select(Deal).options(joinedload(Deal.company))
    if owner:
        deals_q = deals_q.where(Deal.owner == owner)
    flagged = []
    for d in db.scalars(deals_q).unique().all():
        info = deal_flags(d, today)
        if info["is_open"] and ({"inactive", "no_next_step"} & set(info["flags"])):
            flagged.append({
                "deal_id": d.id, "lead_code": d.lead_code, "company": d.company.name if d.company else None,
                "owner": d.owner, "flags": info["flags"], "days_since_contact": info["days_since_contact"],
                "est_value_usd": d.est_value_usd,
            })
    flagged.sort(key=lambda x: -(x["est_value_usd"] or 0))
    failed = db.scalar(select(func.count()).select_from(SourceItem).where(SourceItem.status == "failed")) or 0

    return {
        "date": today.isoformat(),
        "owner": owner,
        "new_drafts": [
            {"id": d.id, "kind": d.kind, "owner": d.owner, "needs_review": d.needs_review,
             "company": (d.fields.get("company") or {}).get("value"),
             "subject": d.source_item.subject if d.source_item else None,
             "age_days": (today - d.created_at.date()).days if d.created_at else None}
            for d in drafts
        ],
        "due_reminders": [
            {"id": r.id, "deal_id": r.deal_id, "lead_code": r.deal.lead_code,
             "company": r.deal.company.name if r.deal.company else None, "reason": r.reason,
             "due_date": r.due_date.isoformat(), "owner": r.owner, "suggested_next_step": r.suggested_next_step}
            for r in reminders
        ],
        "inactive_deals": flagged,
        "integration_failures": failed,
    }


async def scheduler_loop(stop: asyncio.Event) -> None:
    s = get_settings()
    while not stop.is_set():
        try:
            def _run() -> int:
                with SessionLocal() as db:
                    return scan_reminders(db)

            created = await asyncio.to_thread(_run)
            if created:
                log.info("reminder scan created %s reminders", created)
        except Exception:  # pragma: no cover
            log.exception("reminder scan failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=s.reminder_scan_minutes * 60)
        except asyncio.TimeoutError:
            pass
