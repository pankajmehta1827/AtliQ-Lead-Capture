from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serializers as ser
from ..audit import log_action
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import AuditLog, Deal, Draft, ExclusionRule, SourceItem
from ..services.pipeline_health import deal_flags

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/config")
def public_config():
    s = get_settings()
    return {
        "users": s.seller_list,
        "requires_access_code": bool(s.app_access_code),
        "llm_mode": "llm" if s.llm_enabled else "rules",
        "today": s.today().isoformat(),
        "processing_enabled": s.processing_enabled,
        "inactive_days": s.inactive_days,
    }


@router.get("/me")
def me(user: str = Depends(current_user)):
    return {"user": user}


# ---------------------------------------------------------------- exclusions (FR-10)

class ExclusionBody(BaseModel):
    rule_type: Literal["email", "domain", "subject", "keyword"]
    value: str = Field(min_length=2, max_length=300)
    note: str | None = None


@router.get("/exclusions")
def list_exclusions(db: Session = Depends(get_db), _: str = Depends(current_user)):
    return [ser.exclusion(e) for e in db.scalars(select(ExclusionRule).order_by(ExclusionRule.id)).all()]


@router.post("/exclusions")
def add_exclusion(body: ExclusionBody, user: str = Depends(current_user), db: Session = Depends(get_db)):
    rule = ExclusionRule(rule_type=body.rule_type, value=body.value.strip(), note=body.note, created_by=user)
    db.add(rule)
    db.flush()
    log_action(db, actor=user, action="exclusion_added", outcome="ok", entity_type="exclusion", entity_id=rule.id,
               details={"rule_type": rule.rule_type, "value": rule.value})
    db.commit()
    return ser.exclusion(rule)


@router.delete("/exclusions/{rule_id}")
def delete_exclusion(rule_id: int, user: str = Depends(current_user), db: Session = Depends(get_db)):
    rule = db.get(ExclusionRule, rule_id)
    if not rule:
        raise HTTPException(404)
    log_action(db, actor=user, action="exclusion_removed", outcome="ok", entity_type="exclusion", entity_id=rule.id,
               details={"rule_type": rule.rule_type, "value": rule.value})
    db.delete(rule)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- audit (FR-9), read-only

@router.get("/audit")
def list_audit(
    action: str | None = None, actor: str | None = None, limit: int = 200,
    db: Session = Depends(get_db), _: str = Depends(current_user),
):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if action:
        q = q.where(AuditLog.action == action)
    if actor:
        q = q.where(AuditLog.actor == actor)
    return [ser.audit(a) for a in db.scalars(q).all()]


# ---------------------------------------------------------------- kill switch

class ProcessingBody(BaseModel):
    enabled: bool


@router.post("/admin/processing")
def set_processing(body: ProcessingBody, user: str = Depends(current_user), db: Session = Depends(get_db)):
    """PRD kill switch: pause all automatic processing. Queued items wait; nothing is lost."""
    get_settings().processing_enabled = body.enabled
    log_action(db, actor=user, action="kill_switch", outcome="enabled" if body.enabled else "paused")
    db.commit()
    return {"processing_enabled": body.enabled}


# ---------------------------------------------------------------- success metrics (PRD section)

@router.get("/metrics")
def metrics(db: Session = Depends(get_db), _: str = Depends(current_user)):
    s = get_settings()
    today = s.today()
    reviewed = db.scalars(select(Draft).where(Draft.status.in_(["confirmed", "discarded"]))).all()
    confirmed = [d for d in reviewed if d.status == "confirmed"]
    minor = [d for d in confirmed if len(d.edited_fields or []) <= 1]
    new_leads = [d for d in confirmed if d.kind == "new_lead"]
    within_24h = [
        d for d in new_leads
        if d.reviewed_at and d.created_at
        and (d.reviewed_at.replace(tzinfo=None) - d.created_at.replace(tzinfo=None)) <= timedelta(hours=24)
    ]
    complete = [
        d for d in within_24h
        if all((d.fields.get(f) or {}).get("value") for f in ("source", "requirement", "next_step"))
        or d.edited_fields
    ]

    deals = db.scalars(select(Deal)).all()
    open_infos = [deal_flags(d, today) for d in deals]
    open_infos = [i for i in open_infos if i["is_open"]]
    with_next = [i for i in open_infos if "no_next_step" not in i["flags"]]
    inactive = [i for i in open_infos if "inactive" in i["flags"]]

    pending = db.scalars(select(Draft).where(Draft.status == "pending")).all()
    oldest_days = max(((today - d.created_at.date()).days for d in pending), default=0) if pending else 0
    items = dict(db.execute(select(SourceItem.status, func.count()).group_by(SourceItem.status)).all())

    def pct(a: int, b: int) -> float | None:
        return round(100 * a / b, 1) if b else None

    confirmation_rate = pct(len(minor), len(reviewed))
    return {
        "north_star": {
            "label": "New leads recorded within 24h with source, requirement and next step",
            "value": pct(len(complete), len(new_leads)), "target": 95, "n": len(new_leads),
        },
        "pipeline_hygiene": {
            "label": "Open deals with a scheduled next step", "value": pct(len(with_next), len(open_infos)),
            "target": 100, "open_deals": len(open_infos), "inactive_deals": len(inactive),
        },
        "trust": {
            "label": "Drafts confirmed with no or minor edits", "value": confirmation_rate, "target": 80,
            "reviewed": len(reviewed), "confirmed": len(confirmed), "discarded": len(reviewed) - len(confirmed),
        },
        "queue": {"pending_drafts": len(pending), "oldest_pending_days": oldest_days, "items": items},
        "kill_switch_warnings": [
            w for w in [
                "Confirmation rate below 50%: the assistant may be creating more work than it saves."
                if confirmation_rate is not None and len(reviewed) >= 10 and confirmation_rate < 50 else None,
                f"{items.get('failed', 0)} captured item(s) failed processing; check integrations."
                if items.get("failed") else None,
            ] if w
        ],
        "processing_enabled": s.processing_enabled,
    }
