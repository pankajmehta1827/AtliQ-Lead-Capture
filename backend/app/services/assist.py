"""AI assistance on top of the CRM: follow-up email drafts (#4) and 'Ask your pipeline' (#5).

Both read only: they never write to the CRM and never contact a client. Every client-specific fact they
use must quote the context it came from; quotes that can't be found are flagged as unverified."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..audit import log_action
from ..config import get_settings
from ..graph.grounding import evidence_in_source
from ..graph.pipeline import _mentioned_deals
from ..matching import CLOSED_STATUSES
from ..models import Deal, DealActivity, Draft, Reminder, SourceItem
from .pipeline_health import deal_flags

CONVERSATION_CHARS = 2500


def _money(v: float | None) -> str:
    return f"${v / 1000:.0f}k" if v else "value unknown"


def _deal_line(d: Deal, today) -> str:
    info = deal_flags(d, today)
    contact = d.contact.name if d.contact and d.contact.name else "no contact"
    return (
        f"{d.lead_code} | {d.company.name if d.company else '?'} | contact {contact} | status {d.status or 'none'} | "
        f"{_money(d.est_value_usd)} | owner {d.owner or 'none'} | last contact {d.last_contact_date or 'never'} | "
        f"next step {d.next_step or 'none'} | next follow-up {d.next_followup_date or 'none'} | "
        f"flags {', '.join(info['flags']) or 'none'}"
    )


def _conversations(db: Session, deal: Deal, limit: int = 2) -> list[SourceItem]:
    """Most recent saved conversations about this deal (confirmed, pending review, or behind a reminder)."""
    ids: set[int] = set()
    ids.update(x for x in db.scalars(select(DealActivity.source_item_id).where(DealActivity.deal_id == deal.id)) if x)
    ids.update(x for x in db.scalars(select(Draft.source_item_id).where(
        Draft.deal_id == deal.id, Draft.status.in_(["pending", "confirmed"]))) if x)
    ids.update(x for x in db.scalars(select(Reminder.source_item_id).where(Reminder.deal_id == deal.id)) if x)
    if not ids:
        return []
    items = db.scalars(select(SourceItem).where(SourceItem.id.in_(ids), SourceItem.body.is_not(None))).all()
    return sorted(items, key=lambda i: (i.occurred_at is not None, i.occurred_at), reverse=True)[:limit]


def deal_context(db: Session, deal: Deal, reminders: list[Reminder] | None = None, conv_chars: int = CONVERSATION_CHARS) -> str:
    today = get_settings().today()
    parts = [f"Today: {today}", "CRM RECORD", _deal_line(deal, today)]
    if deal.requirement:
        parts.append(f"Requirement: {deal.requirement}")
    if deal.notes:
        parts.append(f"CRM notes: {deal.notes[-1500:]}")
    rems = reminders if reminders is not None else db.scalars(
        select(Reminder).where(Reminder.deal_id == deal.id, Reminder.status == "open")).all()
    if rems:
        parts.append("OPEN FOLLOW-UPS")
        parts += [f"- {r.reason} (due {r.due_date})" + (f' evidence: "{r.evidence}"' if r.evidence else "") for r in rems]
    for si in _conversations(db, deal):
        parts.append(f"CONVERSATION ({si.channel}, {si.occurred_at}, subject: {si.subject})")
        parts.append((si.body or "")[-conv_chars:])
    return "\n".join(parts)


def _check(items: list[dict], context: str, key: str = "evidence") -> list[dict]:
    return [{**x, "grounded": evidence_in_source(x.get(key), context)} for x in items]


# ---------------------------------------------------------------- #4 follow-up email drafts

def draft_email(db: Session, deal: Deal, user: str, instructions: str = "", reminder_ids: list[int] | None = None) -> dict[str, Any]:
    s = get_settings()
    rems = db.scalars(select(Reminder).where(Reminder.deal_id == deal.id, Reminder.status == "open")).all()
    if reminder_ids:
        rems = [r for r in rems if r.id in set(reminder_ids)] or rems
    context = deal_context(db, deal, rems)
    contact = deal.contact.name if deal.contact and deal.contact.name else None
    to_email = deal.contact.email if deal.contact else None
    sender = deal.owner or user

    if s.llm_enabled:
        from ..graph.llm import email_chain

        out = email_chain().invoke({
            "sender": sender, "recipient": contact or f"the {deal.company.name if deal.company else 'client'} team",
            "instructions": instructions.strip()[:500] or "none", "context": context,
        })
        subject, body = out.subject, out.body
        facts = _check([f.model_dump() for f in (out.facts or [])], context)
        mode = "llm"
    else:
        first = (contact or "there").split()[0]
        reason = rems[0].reason if rems else "our recent conversation"
        step = rems[0].suggested_next_step if rems and rems[0].suggested_next_step else "agree on the next step"
        subject = f"Following up: {deal.company.name if deal.company else 'next steps'}"
        body = (
            f"Hi {first},\n\nI wanted to follow up on {reason[0].lower() + reason[1:] if reason else 'our conversation'}. "
            f"Could we {step[0].lower() + step[1:]}? I'm happy to work around your schedule: [your availability].\n\n"
            f"Best regards,\n{sender}\nAtliQ Technologies"
        )
        facts = _check([{"fact": r.reason, "evidence": r.reason} for r in rems[:1]], context)
        mode = "rules"

    log_action(db, actor=user, action="email_drafted", outcome=mode, entity_type="deal", entity_id=deal.id,
               details={"reminders": [r.id for r in rems], "instructions": instructions[:200]})
    db.commit()
    return {
        "deal_id": deal.id, "lead_code": deal.lead_code, "to_name": contact, "to_email": to_email,
        "subject": subject, "body": body, "facts": facts, "mode": mode,
        "unverified": sum(1 for f in facts if not f["grounded"]),
    }


# ---------------------------------------------------------------- #5 ask your pipeline

def ask_pipeline(db: Session, question: str, history: list[dict], user: str) -> dict[str, Any]:
    s = get_settings()
    today = s.today()
    deals = db.scalars(
        select(Deal).options(joinedload(Deal.company), joinedload(Deal.contact)).order_by(Deal.lead_code)
    ).unique().all()
    recent = " ".join(m.get("content", "") for m in history[-2:] if m.get("role") == "user")
    focus_ids = [m["deal_id"] for m in _mentioned_deals(db, f"{question} {recent}")][:3]
    focus = [d for d in deals if d.id in focus_ids]

    snapshot = "\n".join(_deal_line(d, today) for d in deals)
    details = "\n\n".join(f"DETAILS FOR {d.lead_code}\n{deal_context(db, d, conv_chars=1800)}" for d in focus)
    context = (
        f"Signed-in user: {user}. Today: {today}.\nPIPELINE SNAPSHOT (one line per CRM deal; closed = Won/Lost)\n"
        f"{snapshot}" + (f"\n\n{details}" if details else "")
    )

    if s.llm_enabled:
        from ..graph.llm import ask_chain

        msgs = [("human" if m["role"] == "user" else "ai", m["content"][:2000]) for m in history[-6:]
                if m.get("role") in ("user", "assistant") and m.get("content")]
        out = ask_chain().invoke({"context": context, "question": question[:1000], "today": today.isoformat(),
                                  "history": msgs})
        answer = out.answer
        codes = list(dict.fromkeys(out.deals or []))
        citations = _check([c.model_dump() for c in (out.citations or [])], context, key="quote")
        mode = "llm"
    else:
        pool = focus or sorted(
            [d for d in deals if d.status not in CLOSED_STATUSES and deal_flags(d, today)["flags"]],
            key=lambda d: -(d.est_value_usd or 0),
        )[:5]
        answer = ("AI answers need a GROQ_API_KEY. Here is what the CRM shows for the most relevant deals:\n"
                  + "\n".join(f"- {_deal_line(d, today)}" for d in pool))
        codes = [d.lead_code for d in pool]
        citations = []
        mode = "rules"

    by_code = {d.lead_code: d for d in deals}
    linked = [{"lead_code": c, "deal_id": by_code[c].id, "company": by_code[c].company.name if by_code[c].company else None}
              for c in codes if c in by_code]
    log_action(db, actor=user, action="pipeline_question", outcome=mode,
               details={"question": question[:300], "deals": [x["lead_code"] for x in linked]})
    db.commit()
    return {"answer": answer, "deals": linked, "citations": citations, "mode": mode}
