from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def log_action(
    db: Session,
    *,
    actor: str,
    action: str,
    outcome: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    source_ref: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry. Caller owns the transaction so the log commits with the action it describes."""
    entry = AuditLog(
        actor=actor,
        action=action,
        outcome=outcome,
        entity_type=entity_type,
        entity_id=entity_id,
        source_ref=source_ref,
        details=details or {},
    )
    db.add(entry)
    return entry
