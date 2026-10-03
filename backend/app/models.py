"""Database tables.

CRM side:      Company, Contact, Deal, DealActivity, CrossSellSuggestion
Assistant side: SourceItem (captured email/meeting/LinkedIn share), Draft (review queue),
                Reminder, ExclusionRule, AuditLog (append-only, FR-9)
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    domain: Mapped[str | None] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contacts: Mapped[list[Contact]] = relationship(back_populates="company")
    deals: Mapped[list[Deal]] = relationship(back_populates="company")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company | None] = relationship(back_populates="contacts")


class Deal(Base):
    """One CRM lead / opportunity (mirrors a row of crm_export.csv)."""

    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_code: Mapped[str] = mapped_column(String(20), unique=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    source: Mapped[str | None] = mapped_column(String(50))
    service_interest: Mapped[str | None] = mapped_column(String(100))
    requirement: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(30))
    est_value_usd: Mapped[float | None] = mapped_column(Float)
    owner: Mapped[str | None] = mapped_column(String(50))
    created_date: Mapped[date | None] = mapped_column(Date)
    last_contact_date: Mapped[date | None] = mapped_column(Date)
    next_followup_date: Mapped[date | None] = mapped_column(Date)
    next_step: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    company: Mapped[Company | None] = relationship(back_populates="deals")
    contact: Mapped[Contact | None] = relationship()
    activities: Mapped[list[DealActivity]] = relationship(
        back_populates="deal", order_by="DealActivity.occurred_at.desc()"
    )


class SourceItem(Base):
    """A captured conversation. Body is wiped if the item turns out to be excluded / not sales-related."""

    __tablename__ = "source_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))  # email | meeting | linkedin
    external_ref: Mapped[str | None] = mapped_column(String(300), unique=True)
    subject: Mapped[str | None] = mapped_column(String(500))
    sender_name: Mapped[str | None] = mapped_column(String(200))
    sender_email: Mapped[str | None] = mapped_column(String(200))
    participants: Mapped[list] = mapped_column(JSON, default=list)  # [{name, email}]
    occurred_at: Mapped[date | None] = mapped_column(Date)
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    category: Mapped[str | None] = mapped_column(String(30))
    skip_reason: Mapped[str | None] = mapped_column(String(300))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    ingested_by: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Draft(Base):
    """A proposed CRM write waiting in the owner's review queue (FR-4). Nothing reaches `deals` until confirmed."""

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("source_items.id"))
    kind: Mapped[str] = mapped_column(String(20))  # new_lead | update
    category: Mapped[str] = mapped_column(String(30))  # new_lead | existing_deal | existing_client
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"))
    fields: Mapped[dict] = mapped_column(JSON, default=dict)  # {field: {value, evidence, confidence}}
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    duplicate_candidates: Mapped[list] = mapped_column(JSON, default=list)
    followups: Mapped[list] = mapped_column(JSON, default=list)
    crosssell: Mapped[list] = mapped_column(JSON, default=list)
    owner: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    edited_fields: Mapped[list] = mapped_column(JSON, default=list)
    discard_reason: Mapped[str | None] = mapped_column(String(300))
    reviewed_by: Mapped[str | None] = mapped_column(String(50))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llm_mode: Mapped[str] = mapped_column(String(20), default="llm")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source_item: Mapped[SourceItem] = relationship()
    deal: Mapped[Deal | None] = relationship()


class DealActivity(Base):
    """Timeline entry linking a deal to the conversation that changed it (FR-8)."""

    __tablename__ = "deal_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    source_item_id: Mapped[int | None] = mapped_column(ForeignKey("source_items.id"))
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"))
    occurred_at: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deal: Mapped[Deal] = relationship(back_populates="activities")
    source_item: Mapped[SourceItem | None] = relationship()


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # commitment | proposal_unanswered | inactive | no_next_step
    reason: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    suggested_next_step: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    source_item_id: Mapped[int | None] = mapped_column(ForeignKey("source_items.id"))
    owner: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | done | dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    deal: Mapped[Deal] = relationship()
    source_item: Mapped[SourceItem | None] = relationship()


class CrossSellSuggestion(Base):
    __tablename__ = "crosssell_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    service: Mapped[str] = mapped_column(String(100))
    rationale: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    source_item_id: Mapped[int | None] = mapped_column(ForeignKey("source_items.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deal: Mapped[Deal] = relationship()


class ExclusionRule(Base):
    """FR-10: contacts, domains, subjects or keywords the assistant must never process."""

    __tablename__ = "exclusion_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(20))  # email | domain | subject | keyword
    value: Mapped[str] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """FR-9: append-only log of every assistant and user action. No update/delete endpoints exist."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(50))  # user name or "assistant"
    action: Mapped[str] = mapped_column(String(50), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    source_ref: Mapped[str | None] = mapped_column(String(300))
    outcome: Mapped[str] = mapped_column(String(50))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
