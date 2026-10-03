"""Owner review of drafts (FR-4). This module is the ONLY place that writes assistant output into the CRM,
and it only runs on an explicit confirm by a user."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import log_action
from ..catalogue import STAGES
from ..matching import normalize_company
from ..models import Company, Contact, CrossSellSuggestion, Deal, DealActivity, Draft, Reminder
from ..parsing import email_domain

EDITABLE_FIELDS = [
    "company", "contact_name", "contact_email", "source", "service_interest", "requirement",
    "budget", "timeline", "stage", "next_step", "next_step_date",
]


def _parse_money(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(k|m)?", text.lower().replace("$", ""))
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    if m.group(2) == "k":
        value *= 1_000
    elif m.group(2) == "m":
        value *= 1_000_000
    return value if value >= 1000 else None


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _next_lead_code(db: Session) -> str:
    codes = db.scalars(select(Deal.lead_code)).all()
    nums = [int(c.split("-")[1]) for c in codes if re.fullmatch(r"L-\d+", c)]
    return f"L-{(max(nums) + 1) if nums else 1001}"


def _get_or_create_company(db: Session, name: str, contact_email: str | None) -> Company:
    norm = normalize_company(name)
    company = db.scalar(select(Company).where(Company.normalized_name == norm))
    if company:
        return company
    company = Company(name=name, normalized_name=norm, domain=email_domain(contact_email))
    db.add(company)
    db.flush()
    return company


def _get_or_create_contact(db: Session, company: Company | None, name: str | None, email: str | None) -> Contact | None:
    if not name and not email:
        return None
    if email:
        existing = db.scalar(select(Contact).where(func.lower(Contact.email) == email.lower()))
        if existing:
            return existing
    contact = Contact(company_id=company.id if company else None, name=name, email=email)
    db.add(contact)
    db.flush()
    return contact


def confirm_draft(
    db: Session,
    draft: Draft,
    user: str,
    edits: dict[str, Any] | None = None,
    target_deal_id: int | None = None,
    create_new: bool = False,
) -> Deal:
    if draft.status != "pending":
        raise HTTPException(409, f"Draft already {draft.status}")
    edits = {k: v for k, v in (edits or {}).items() if k in EDITABLE_FIELDS}

    values: dict[str, Any] = {k: (draft.fields.get(k) or {}).get("value") for k in EDITABLE_FIELDS}
    edited = []
    for k, v in edits.items():
        v = v.strip() if isinstance(v, str) else v
        if (v or None) != values.get(k):
            edited.append(k)
        values[k] = v or None
    if values.get("stage") and values["stage"] not in STAGES:
        raise HTTPException(422, f"stage must be one of {STAGES}")

    occurred = draft.source_item.occurred_at if draft.source_item else None
    deal_id = None if create_new else (target_deal_id or draft.deal_id)
    changes: dict[str, Any] = {}

    if deal_id:
        deal = db.get(Deal, deal_id)
        if not deal:
            raise HTTPException(404, "Target deal not found")

        def _set(attr: str, new: Any) -> None:
            old = getattr(deal, attr)
            if new not in (None, "") and new != old:
                changes[attr] = {"from": str(old) if old is not None else None, "to": str(new)}
                setattr(deal, attr, new)

        _set("service_interest", values.get("service_interest"))
        _set("requirement", values.get("requirement"))
        _set("status", values.get("stage"))
        _set("est_value_usd", _parse_money(values.get("budget")))
        _set("next_step", values.get("next_step"))
        _set("next_followup_date", _parse_date(values.get("next_step_date")))
        if not deal.owner and draft.owner:
            _set("owner", draft.owner)
        if values.get("contact_email") and (not deal.contact or not deal.contact.email):
            contact = _get_or_create_contact(db, deal.company, values.get("contact_name"), values["contact_email"])
            if contact:
                _set("contact_id", contact.id)
        action = "deal_updated"
    else:
        if not values.get("company"):
            raise HTTPException(422, "Company is required to create a new lead")
        company = _get_or_create_company(db, values["company"], values.get("contact_email"))
        contact = _get_or_create_contact(db, company, values.get("contact_name"), values.get("contact_email"))
        deal = Deal(
            lead_code=_next_lead_code(db),
            company_id=company.id,
            contact_id=contact.id if contact else None,
            source=values.get("source"),
            service_interest=values.get("service_interest"),
            requirement=values.get("requirement"),
            status=values.get("stage") or "New",
            est_value_usd=_parse_money(values.get("budget")),
            owner=draft.owner,
            created_date=occurred or date.today(),
            next_step=values.get("next_step"),
            next_followup_date=_parse_date(values.get("next_step_date")),
        )
        db.add(deal)
        db.flush()
        changes = {"created": deal.lead_code}
        action = "deal_created"

    if occurred and (not deal.last_contact_date or occurred > deal.last_contact_date):
        changes["last_contact_date"] = {"from": str(deal.last_contact_date), "to": str(occurred)}
        deal.last_contact_date = occurred
    if draft.summary or values.get("timeline"):
        note = f"[{occurred or date.today()}] {draft.summary or ''}"
        if values.get("timeline"):
            note += f" Timeline: {values['timeline']}."
        deal.notes = f"{deal.notes}\n{note}" if deal.notes else note

    db.add(
        DealActivity(
            deal_id=deal.id, source_item_id=draft.source_item_id, draft_id=draft.id, occurred_at=occurred,
            summary=draft.summary, changes=changes, actor=user,
        )
    )

    # Reminders from detected follow-up signals (FR-6). Reminders go to AtliQ users only.
    created_reminders = 0
    followups = list(draft.followups or [])
    if "next_step_date" in edited and values.get("next_step_date"):
        followups.append({
            "reason": f"Next step: {values.get('next_step') or 'follow up'}", "due_date": values["next_step_date"],
            "suggested_next_step": values.get("next_step"), "evidence": "Set by owner during review",
        })
    for f in followups:
        due = _parse_date(f.get("due_date"))
        if not due:
            continue
        exists = db.scalar(
            select(Reminder).where(Reminder.deal_id == deal.id, Reminder.due_date == due, Reminder.status == "open",
                                   Reminder.kind == "commitment")
        )
        if exists:
            continue
        db.add(Reminder(
            deal_id=deal.id, kind="commitment", reason=f["reason"], due_date=due,
            suggested_next_step=f.get("suggested_next_step"), evidence=f.get("evidence"),
            source_item_id=draft.source_item_id, owner=deal.owner or draft.owner,
        ))
        created_reminders += 1

    for idea in draft.crosssell or []:
        db.add(CrossSellSuggestion(
            deal_id=deal.id, service=idea.get("service") or "Unclassified need", rationale=idea["rationale"],
            evidence=idea.get("evidence"), source_item_id=draft.source_item_id,
        ))

    draft.status = "confirmed"
    draft.deal_id = deal.id
    draft.edited_fields = edited
    draft.reviewed_by = user
    draft.reviewed_at = datetime.now(timezone.utc)
    log_action(
        db, actor=user, action="draft_confirmed", outcome=action, entity_type="draft", entity_id=draft.id,
        source_ref=draft.source_item.external_ref if draft.source_item else None,
        details={"deal": deal.lead_code, "edited_fields": edited, "changes": changes, "reminders": created_reminders},
    )
    db.commit()
    db.refresh(deal)
    return deal


def discard_draft(db: Session, draft: Draft, user: str, reason: str | None) -> None:
    if draft.status != "pending":
        raise HTTPException(409, f"Draft already {draft.status}")
    draft.status = "discarded"
    draft.discard_reason = reason
    draft.reviewed_by = user
    draft.reviewed_at = datetime.now(timezone.utc)
    log_action(
        db, actor=user, action="draft_discarded", outcome="discarded", entity_type="draft", entity_id=draft.id,
        source_ref=draft.source_item.external_ref if draft.source_item else None, details={"reason": reason},
    )
    db.commit()
