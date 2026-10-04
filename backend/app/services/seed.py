"""Load the existing CRM export and the sample mailbox/meeting-notes dataset."""
from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import log_action
from ..catalogue import DATA_DIR, STAGES
from ..matching import normalize_company
from ..models import Company, Contact, Deal, DealActivity
from ..parsing import email_domain, parse_markdown_item
from .capture import enqueue_item

# Column layout of crm_export.csv; export uses the same order so files round-trip.
CRM_COLUMNS = [
    "lead_id", "company", "contact_name", "contact_email", "source", "service_interest", "status",
    "est_value_usd", "owner", "created_date", "last_contact_date", "next_followup_date", "notes",
]


def _d(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _s(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _next_code(db: Session) -> str:
    nums = [int(c[2:]) for c in db.scalars(select(Deal.lead_code)).all() if re.fullmatch(r"L-\d+", c)]
    return f"L-{(max(nums) + 1) if nums else 1001}"


def upsert_crm_rows(
    db: Session, rows: Iterable[dict[str, Any]], actor: str, source_name: str, update_existing: bool
) -> dict[str, Any]:
    """Create deals for new lead_ids; for existing ones, overwrite only the cells that are filled in.
    Rows without a lead_id get a new one. Every change is recorded on the deal's activity timeline."""
    created = updated = skipped = 0
    errors: list[str] = []
    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        row = {k.strip().lower(): v for k, v in raw.items() if k}
        company_name = _s(row.get("company"))
        if not company_name:
            skipped += 1
            continue
        status = _s(row.get("status"))
        if status and status not in STAGES:
            errors.append(f"row {i}: unknown status '{status}' (kept blank)")
            status = None
        code = _s(row.get("lead_id"))
        deal = db.scalar(select(Deal).where(Deal.lead_code == code)) if code else None
        email = _s(row.get("contact_email"))
        email = email.lower() if email else None

        if deal and not update_existing:
            skipped += 1
            continue

        norm = normalize_company(company_name)
        company = db.scalar(select(Company).where(Company.normalized_name == norm))
        if not company:
            company = Company(name=company_name, normalized_name=norm, domain=email_domain(email))
            db.add(company)
            db.flush()
        contact = None
        contact_name = _s(row.get("contact_name"))
        if email:
            contact = db.scalar(select(Contact).where(func.lower(Contact.email) == email))
        elif contact_name:  # no email: same name at the same company is the same person
            contact = db.scalar(select(Contact).where(
                Contact.company_id == company.id, func.lower(Contact.name) == contact_name.lower()))
        if not contact and (contact_name or email):
            contact = Contact(company_id=company.id, name=contact_name, email=email)
            db.add(contact)
            db.flush()

        values = {
            "company_id": company.id,
            "contact_id": contact.id if contact else None,
            "source": _s(row.get("source")),
            "service_interest": _s(row.get("service_interest")),
            "status": status,
            "est_value_usd": _money(row.get("est_value_usd")),
            "owner": _s(row.get("owner")),
            "created_date": _d(row.get("created_date")),
            "last_contact_date": _d(row.get("last_contact_date")),
            "next_followup_date": _d(row.get("next_followup_date")),
            "notes": _s(row.get("notes")),
        }
        if deal:
            changes = {}
            for k, v in values.items():
                if v is not None and v != getattr(deal, k):
                    changes[k] = {"from": str(getattr(deal, k)), "to": str(v)}
                    setattr(deal, k, v)
            if changes:
                db.add(DealActivity(deal_id=deal.id, summary=f"Updated by import ({source_name})", changes=changes, actor=actor))
                updated += 1
        else:
            deal = Deal(lead_code=code or _next_code(db), **values)
            deal.created_date = deal.created_date or date.today()
            db.add(deal)
            db.flush()
            if actor != "system":
                db.add(DealActivity(deal_id=deal.id, summary=f"Created by import ({source_name})",
                                    changes={"created": deal.lead_code}, actor=actor))
            created += 1
    log_action(db, actor=actor, action="crm_import", outcome="ok",
               details={"file": source_name, "created": created, "updated": updated, "skipped": skipped, "errors": errors[:20]})
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def import_crm_csv(db: Session, path: Path | None = None) -> int:
    path = path or DATA_DIR / "crm_export.csv"
    with path.open(encoding="utf-8") as fh:
        return upsert_crm_rows(db, csv.DictReader(fh), "system", path.name, update_existing=False)["created"]


def sample_files() -> list[Path]:
    return sorted((DATA_DIR / "emails").glob("*.md")) + sorted((DATA_DIR / "meeting_notes").glob("*.md"))


def ingest_sample_dataset(db: Session, user: str, limit: int | None = None) -> dict[str, int]:
    """Simulates the mailbox + calendar connectors (FR-1) using the bundled dataset."""
    queued = existing = 0
    for path in sample_files()[:limit]:
        channel = "meeting" if path.parent.name == "meeting_notes" else "email"
        parsed = parse_markdown_item(path.read_text(encoding="utf-8"), f"{path.parent.name}/{path.name}", channel)
        _, created = enqueue_item(db, parsed, user)
        queued += created
        existing += not created
    return {"queued": queued, "already_captured": existing}
