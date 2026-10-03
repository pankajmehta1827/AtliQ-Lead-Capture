"""Rule-based fallback used when no GROQ_API_KEY is configured (local demo / tests / LLM outage).
Deliberately conservative: low confidence, so every draft lands in 'needs review'."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from ..catalogue import load_catalogue

SALES_WORDS = re.compile(
    r"(?i)\b(proposal|budget|quote|pricing|price|demo|discovery|scope|sow|contract|renewal|requirement|"
    r"dashboard|project|engagement|partner|intro|referr|rates|engineers?|poc|prototype|commercial|deal|phase)\w*"
)
PERSONAL_WORDS = re.compile(r"(?i)\b(birthday|dinner|wedding|vacation|holiday plans|family|newsletter|unsubscribe)\b")
ACTION_RE = re.compile(
    r"(?i)[^.?!\n]*\b(will|shall|please|can you|could you|send|schedule|call|follow up|check back|confirm|by \d{1,2} \w+|"
    r"due|deadline|proposal)\b[^.?!\n]*(?:[.?!\n]|$)"
)
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DAY_MONTH_RE = re.compile(r"(?i)\bby\s+(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*")
QUARTER_RE = re.compile(r"(?i)\bQ([1-4])\s*(20\d{2})?")


def _field(value: Any, evidence: str | None, confidence: float = 0.5) -> dict:
    return {"value": value, "evidence": evidence, "confidence": confidence if value else 0.0}


def _sentences(body: str) -> list[str]:
    text = re.sub(r"(?m)^(#.*|\*\*\w+:\*\*.*|---)$", "", body)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -*[]") for p in parts if len(p.strip()) > 25]


def resolve_date(text: str, ref: date) -> str | None:
    m = DAY_MONTH_RE.search(text)
    if m:
        d = date(ref.year, MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        if d < ref - timedelta(days=180):
            d = d.replace(year=d.year + 1)
        return d.isoformat()
    m = QUARTER_RE.search(text)
    if m:
        year = int(m.group(2)) if m.group(2) else ref.year
        return date(year, 3 * (int(m.group(1)) - 1) + 1, 1).isoformat()
    return None


def classify(item: dict, has_match: bool, all_internal: bool) -> dict:
    body = item.get("body") or ""
    if PERSONAL_WORDS.search(body) and not SALES_WORDS.search(body):
        return {"category": "not_sales", "confidence": 0.6, "reason": "Looks personal / non-business (rule-based)."}
    hits = len(SALES_WORDS.findall(body))
    if all_internal and not has_match:
        return {"category": "not_sales", "confidence": 0.55, "reason": "Internal-only conversation with no single client (rule-based)."}
    if hits == 0 and not has_match:
        return {"category": "not_sales", "confidence": 0.5, "reason": "No sales vocabulary found (rule-based)."}
    category = "existing_deal" if has_match else "new_lead"
    return {"category": category, "confidence": min(0.9, 0.5 + 0.05 * hits), "reason": f"{hits} sales signals found (rule-based)."}


def extract(item: dict, crm: dict | None, today: date, internal_domain: str = "atliq.com") -> dict:
    body = item.get("body") or ""
    sentences = _sentences(body)
    title = item.get("title") or ""
    company = None
    stripped = re.sub(r"(?i)^(email thread|email|meeting notes|notes|call)\s*[:—–-]?\s*", "", title)
    m = re.match(r"([^—–,(]+?)\s*(?:[—–,(]|$)", stripped)
    if m and m.group(1).strip().lower() not in {"internal", "email", ""}:
        company = re.sub(r"(?i)\s+(demo|call|check|status\??|intro.*)$", "", m.group(1).strip()).strip(" ?")
    if not company and crm:
        company = crm.get("company")
    external = [p for p in item.get("participants", []) if p.get("email") and not p["email"].endswith("@" + internal_domain)]
    contact = external[0] if external else None

    service, service_ev = None, None
    lowered = body.lower()
    for svc in load_catalogue():
        for need in [svc["name"]] + svc["typical_needs"]:
            key = need.lower().split(" (")[0].split(" / ")[0]
            if key in lowered:
                service = svc["name"]
                idx = lowered.index(key)
                service_ev = body[idx: idx + len(key)]
                break
        if service:
            break

    actions = [m.group(0).strip() for m in ACTION_RE.finditer(body)]
    next_step = actions[-1] if actions else None
    next_date = resolve_date(next_step, today) if next_step else None

    followups = []
    for a in actions:
        due = resolve_date(a, today)
        if due:
            followups.append({
                "reason": a[:160], "due_date": due, "suggested_next_step": a[:160],
                "owner_is_atliq": True, "evidence": a,
            })

    budget = re.search(r"(?i)(budget[^.\n]{0,60}?\d[\d,.]*\s?k?|\$\s?\d[\d,.]*\s?k?|\d[\d,.]*\s?k\b[^.\n]{0,20})", body)
    return {
        "company": _field(company, company if company and company in body else None),
        "contact_name": _field(contact.get("name") if contact else None, contact.get("name") if contact else None),
        "contact_email": _field(contact.get("email") if contact else None, contact.get("email") if contact else None),
        "source": _field(None, None),
        "service_interest": _field(service, service_ev, 0.45),
        "requirement": _field(item.get("subject"), item.get("subject"), 0.4),
        "budget": _field(budget.group(0).strip() if budget else None, budget.group(0).strip() if budget else None),
        "timeline": _field(None, None),
        "stage": _field(None, None),
        "next_step": _field(next_step, next_step, 0.4),
        "next_step_date": _field(next_date, next_step if next_date else None, 0.4),
        "summary": [{"text": s, "evidence": s} for s in sentences[:4]],
        "followups": followups,
        "new_needs": [],
    }
