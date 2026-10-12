"""Remove captured conversations and everything they produced, so a scenario can be captured again (demo and
eval resets). Confirmed CRM changes are reverted from the before-values the deal timeline recorded; the action
log is append-only and keeps a record of the removal."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, Integer, delete, select
from sqlalchemy.orm import Session

from ..audit import log_action
from ..models import CrossSellSuggestion, Deal, DealActivity, Draft, Reminder, SourceItem


def _restore(deal: Deal, attr: str, before: str | None) -> None:
    col = Deal.__table__.c[attr]
    if before in (None, "None", ""):
        value: Any = None
    elif isinstance(col.type, Date):
        value = date.fromisoformat(before[:10])
    elif isinstance(col.type, Float):
        value = float(before)
    elif isinstance(col.type, Integer):
        value = int(before)
    else:
        value = before
    setattr(deal, attr, value)


def _drop_note(deal: Deal, summary: str | None) -> None:
    """Confirming a draft appends "[date] summary" to the deal notes; take that line back out."""
    if not deal.notes or not summary:
        return
    lines = deal.notes.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("[") and summary in lines[i]:
            del lines[i]
            break
    deal.notes = "\n".join(lines) or None


def _delete_deal(db: Session, deal: Deal) -> None:
    for model in (Reminder, CrossSellSuggestion, DealActivity):
        db.execute(delete(model).where(model.deal_id == deal.id))
    db.execute(delete(Draft).where(Draft.deal_id == deal.id, Draft.status != "confirmed"))
    for d in db.scalars(select(Draft).where(Draft.deal_id == deal.id)).all():
        d.deal_id = None
    db.delete(deal)


def remove_conversations(db: Session, ids: list[int], user: str) -> dict[str, Any]:
    report: dict[str, Any] = {"removed": [], "not_found": [], "deals_reverted": [], "deals_deleted": []}
    for item_id in ids:
        si = db.get(SourceItem, item_id)
        if not si:
            report["not_found"].append(item_id)
            continue
        draft_ids = list(db.scalars(select(Draft.id).where(Draft.source_item_id == item_id)))
        activities = db.scalars(
            select(DealActivity).where(
                (DealActivity.source_item_id == item_id) | (DealActivity.draft_id.in_(draft_ids or [-1]))
            ).order_by(DealActivity.id.desc())
        ).all()
        for act in activities:  # newest first, so each field returns to the value before this conversation
            deal = db.get(Deal, act.deal_id)
            changes = act.changes or {}
            db.delete(act)
            if not deal:
                continue
            if "created" in changes:
                db.flush()
                _delete_deal(db, deal)
                report["deals_deleted"].append(changes["created"])
                continue
            for attr, ch in changes.items():
                if isinstance(ch, dict) and "from" in ch and attr in Deal.__table__.c:
                    _restore(deal, attr, ch["from"])
            _drop_note(deal, act.summary)
            report["deals_reverted"].append(deal.lead_code)
        db.flush()  # timeline rows reference the drafts: remove them before the drafts (Postgres enforces the FK)
        db.execute(delete(Reminder).where(Reminder.source_item_id == item_id))
        db.execute(delete(CrossSellSuggestion).where(CrossSellSuggestion.source_item_id == item_id))
        db.execute(delete(Draft).where(Draft.source_item_id == item_id))
        report["removed"].append({"id": item_id, "ref": si.external_ref, "drafts": len(draft_ids)})
        db.delete(si)
    log_action(db, actor=user, action="conversations_removed", outcome="removed", details=report)
    db.commit()
    return report
