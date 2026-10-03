"""Deterministic entity matching (FR-5): find existing CRM deals a conversation belongs to.

Deterministic on purpose: the PRD's duplicate-matching eval demands zero wrong merges, and every match
must be explainable to the owner ("same email domain", "company name 92% similar")."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .models import Deal
from .parsing import email_domain

GENERIC_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me", "protonmail.com",
    "live.com", "rediffmail.com", "aol.com",
}
_SUFFIXES = {
    "group", "inc", "llc", "ltd", "limited", "pvt", "private", "co", "corp", "corporation", "plc",
    "the", "and", "&",
}
CLOSED_STATUSES = {"Won", "Lost"}


def normalize_company(name: str | None) -> str:
    if not name:
        return ""
    tokens = re.sub(r"[^a-z0-9& ]+", " ", name.lower()).split()
    return " ".join(t for t in tokens if t not in _SUFFIXES)


def company_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_company(a), normalize_company(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # "meridian health" vs "meridian healthcare": first token identical and one contains the other
    ta, tb = na.split(), nb.split()
    if ta[0] == tb[0] and (na in nb or nb in na or ta[0] == na or tb[0] == nb):
        ratio = max(ratio, 0.9)
    return ratio


def find_matches(
    db: Session,
    *,
    company: str | None,
    emails: list[str],
    contact_name: str | None = None,
    threshold: float = 0.82,
) -> list[dict[str, Any]]:
    emails = [e.lower() for e in emails if e]
    domains = {d for d in (email_domain(e) for e in emails) if d and d not in GENERIC_DOMAINS}
    deals = db.scalars(select(Deal).options(joinedload(Deal.company), joinedload(Deal.contact))).unique().all()

    results: list[dict[str, Any]] = []
    for deal in deals:
        reasons: list[str] = []
        score = 0.0
        contact_email = (deal.contact.email or "").lower() if deal.contact else ""
        contact_domain = email_domain(contact_email)
        if contact_email and contact_email in emails:
            score = 1.0
            reasons.append(f"same contact email ({contact_email})")
        elif contact_domain and contact_domain in domains:
            score = max(score, 0.92)
            reasons.append(f"same email domain ({contact_domain})")
        company_name = deal.company.name if deal.company else None
        sim = company_similarity(company, company_name)
        if sim >= threshold:
            if sim > score:
                score = sim
            reasons.append(f"company name {int(sim * 100)}% similar ('{company_name}')")
        if contact_name and deal.contact and deal.contact.name:
            if SequenceMatcher(None, contact_name.lower(), deal.contact.name.lower()).ratio() > 0.85:
                score = min(1.0, score + 0.03) if score else score
                reasons.append("same contact name")
        if score >= threshold:
            results.append(
                {
                    "deal_id": deal.id,
                    "lead_code": deal.lead_code,
                    "company": company_name,
                    "contact": deal.contact.name if deal.contact else None,
                    "status": deal.status,
                    "owner": deal.owner,
                    "service_interest": deal.service_interest,
                    "score": round(score, 2),
                    "reasons": reasons,
                }
            )

    # Best first: highest score, then open deals before closed ones, then most recently touched.
    results.sort(
        key=lambda r: (
            -r["score"],
            r["status"] in CLOSED_STATUSES,
            -(int(r["lead_code"].split("-")[-1]) if r["lead_code"].split("-")[-1].isdigit() else 0),
        )
    )
    return results
