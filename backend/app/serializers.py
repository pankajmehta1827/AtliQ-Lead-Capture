from __future__ import annotations

from datetime import date
from typing import Any

from .config import get_settings
from .models import AuditLog, CrossSellSuggestion, Deal, Draft, ExclusionRule, Reminder, SourceItem
from .services.pipeline_health import deal_flags, reminder_deadline, reminder_priority


def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def source_item(si: SourceItem | None, with_body: bool = False) -> dict | None:
    if not si:
        return None
    out = {
        "id": si.id, "channel": si.channel, "external_ref": si.external_ref, "subject": si.subject,
        "sender_name": si.sender_name, "sender_email": si.sender_email, "participants": si.participants or [],
        "occurred_at": _iso(si.occurred_at), "status": si.status, "category": si.category,
        "skip_reason": si.skip_reason, "attempts": si.attempts, "last_error": si.last_error,
        "ingested_by": si.ingested_by, "created_at": _iso(si.created_at), "processed_at": _iso(si.processed_at),
    }
    if with_body:
        out["body"] = si.body
    return out


def draft(d: Draft, with_source: bool = False) -> dict:
    return {
        "id": d.id, "kind": d.kind, "category": d.category, "deal_id": d.deal_id,
        "deal_lead_code": d.deal.lead_code if d.deal else None,
        "fields": d.fields, "summary": d.summary, "confidence": d.confidence, "needs_review": d.needs_review,
        "missing_fields": d.missing_fields, "duplicate_candidates": d.duplicate_candidates,
        "followups": d.followups, "crosssell": d.crosssell, "owner": d.owner, "status": d.status,
        "edited_fields": d.edited_fields, "discard_reason": d.discard_reason, "reviewed_by": d.reviewed_by,
        "reviewed_at": _iso(d.reviewed_at), "llm_mode": d.llm_mode, "created_at": _iso(d.created_at),
        "source": source_item(d.source_item, with_body=with_source),
    }


def deal(d: Deal, today: date | None = None) -> dict:
    today = today or get_settings().today()
    info = deal_flags(d, today)
    return {
        "id": d.id, "lead_code": d.lead_code,
        "company": d.company.name if d.company else None, "company_id": d.company_id,
        "contact_name": d.contact.name if d.contact else None,
        "contact_email": d.contact.email if d.contact else None,
        "source": d.source, "service_interest": d.service_interest, "requirement": d.requirement,
        "status": d.status, "est_value_usd": d.est_value_usd, "owner": d.owner,
        "created_date": _iso(d.created_date), "last_contact_date": _iso(d.last_contact_date),
        "next_followup_date": _iso(d.next_followup_date), "next_step": d.next_step, "notes": d.notes,
        **info,
    }


def reminder(r: Reminder) -> dict:
    return {
        "id": r.id, "deal_id": r.deal_id, "lead_code": r.deal.lead_code if r.deal else None,
        "company": r.deal.company.name if r.deal and r.deal.company else None,
        "kind": r.kind, "reason": r.reason, "due_date": _iso(r.due_date),
        "suggested_next_step": r.suggested_next_step, "evidence": r.evidence, "owner": r.owner,
        "status": r.status, "created_at": _iso(r.created_at), "resolved_at": _iso(r.resolved_at),
        "source": source_item(r.source_item),
        "last_message": (r.source_item.body or "")[-600:] if r.source_item and r.source_item.body else None,
        "contact_name": r.deal.contact.name if r.deal and r.deal.contact else None,
        "deal_status": r.deal.status if r.deal else None,
        "est_value_usd": r.deal.est_value_usd if r.deal else None,
        "priority": reminder_priority(r, get_settings().today()),
        "deadline": _iso(reminder_deadline(r)),
    }


def crosssell(c: CrossSellSuggestion) -> dict:
    return {
        "id": c.id, "deal_id": c.deal_id, "lead_code": c.deal.lead_code if c.deal else None,
        "company": c.deal.company.name if c.deal and c.deal.company else None,
        "service": c.service, "rationale": c.rationale, "evidence": c.evidence,
        "source_item_id": c.source_item_id, "status": c.status, "created_at": _iso(c.created_at),
    }


def exclusion(e: ExclusionRule) -> dict:
    return {"id": e.id, "rule_type": e.rule_type, "value": e.value, "note": e.note,
            "created_by": e.created_by, "created_at": _iso(e.created_at)}


def audit(a: AuditLog) -> dict:
    return {"id": a.id, "ts": _iso(a.ts), "actor": a.actor, "action": a.action, "entity_type": a.entity_type,
            "entity_id": a.entity_id, "source_ref": a.source_ref, "outcome": a.outcome, "details": a.details}
