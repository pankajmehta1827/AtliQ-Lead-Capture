"""Load the existing CRM export and the sample mailbox/meeting-notes dataset."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import log_action
from ..catalogue import DATA_DIR
from ..matching import normalize_company
from ..models import Company, Contact, Deal
from ..parsing import email_domain, parse_markdown_item
from .capture import enqueue_item


def _d(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def import_crm_csv(db: Session, path: Path | None = None) -> int:
    path = path or DATA_DIR / "crm_export.csv"
    created = 0
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if db.scalar(select(Deal).where(Deal.lead_code == row["lead_id"])):
                continue
            norm = normalize_company(row["company"])
            company = db.scalar(select(Company).where(Company.normalized_name == norm))
            if not company:
                company = Company(name=row["company"], normalized_name=norm, domain=email_domain(row["contact_email"]))
                db.add(company)
                db.flush()
            contact = None
            if row["contact_email"]:
                contact = db.scalar(select(Contact).where(func.lower(Contact.email) == row["contact_email"].lower()))
            if not contact and (row["contact_name"] or row["contact_email"]):
                contact = Contact(company_id=company.id, name=row["contact_name"] or None, email=row["contact_email"] or None)
                db.add(contact)
                db.flush()
            db.add(Deal(
                lead_code=row["lead_id"], company_id=company.id, contact_id=contact.id if contact else None,
                source=row["source"] or None, service_interest=row["service_interest"] or None,
                status=row["status"] or None,
                est_value_usd=float(row["est_value_usd"]) if row["est_value_usd"] else None,
                owner=row["owner"] or None, created_date=_d(row["created_date"]),
                last_contact_date=_d(row["last_contact_date"]), next_followup_date=_d(row["next_followup_date"]),
                notes=row["notes"] or None,
            ))
            created += 1
    log_action(db, actor="system", action="crm_import", outcome="ok", details={"created": created, "file": path.name})
    db.commit()
    return created


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
