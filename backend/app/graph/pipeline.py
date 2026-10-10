"""LangGraph capture pipeline — implements the PRD decision flow:

  exclusions -> mask -> classify -> extract -> ground -> dates -> match -> assess -> (cross-sell) -> END
       |                   |    \
       |                   |     +-- internal note about several deals -> multi_extract -> END (one draft per deal)
       +-- skip & log -----+-- not sales: skip & log

The graph never writes to the CRM. It returns a proposed draft; persistence and the review queue
live in services.capture."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..catalogue import service_names
from ..config import get_settings
from ..masking import mask_sensitive
from ..matching import CLOSED_STATUSES, company_similarity, find_matches, normalize_company
from ..models import Deal, ExclusionRule
from ..parsing import email_domain, is_internal
from . import heuristics
from .grounding import evidence_in_source, ground_extraction

LEAD_CODE_RE = re.compile(r"\bL-\d{4}\b")
KEY_FIELDS_NEW = ["company", "contact_name", "requirement", "next_step"]
KEY_FIELDS_UPDATE = ["next_step"]  # the deal already holds company, contact and requirement


class CaptureState(TypedDict, total=False):
    item: dict[str, Any]
    ingested_by: str
    skipped: bool
    skip_reason: str
    masked_body: str
    masked_counts: dict[str, int]
    pre_matches: list[dict]
    classification: dict
    extraction: dict
    dropped_fields: list[str]
    crm_context: str
    matches: list[dict]
    kind: str
    category: str
    deal_id: int | None
    owner: str | None
    confidence: float
    needs_review: bool
    missing_fields: list[str]
    followups: list[dict]
    crosssell: list[dict]
    mentioned: list[dict]
    date_signals: list[dict]
    multi_updates: list[dict]
    llm_mode: str
    trace: list[str]


def _db(config: RunnableConfig) -> Session:
    return config["configurable"]["db"]


def _trace(state: CaptureState, msg: str) -> list[str]:
    return [*state.get("trace", []), msg]


def _external_emails(item: dict) -> list[str]:
    domain = get_settings().internal_domain
    return [p["email"] for p in item.get("participants", []) if p.get("email") and not is_internal(p["email"], domain)]


def _conversation_text(item: dict, body: str) -> str:
    header = f"Channel: {item.get('channel')}\nDate: {item.get('occurred_at')}\nSubject: {item.get('subject')}\n"
    return header + "\n" + body[:6000]  # keeps a call well inside small tokens-per-minute tiers


_GENERIC_KEYS = {"group", "health", "data", "global", "smart", "city", "green", "blue", "the", "first", "trust", "cloud"}


def _mentioned_deals(db: Session, text: str) -> list[dict]:
    """CRM deals named in the text by lead id or by a distinctive company word (e.g. 'FinEdge', 'NovaPharma')."""
    low = text.lower()
    out, seen = [], set()
    for deal in db.scalars(select(Deal)).all():
        name = deal.company.name if deal.company else ""
        key = (normalize_company(name).split() or [""])[0]
        hit = deal.lead_code in text or (
            len(key) >= 4 and key not in _GENERIC_KEYS and re.search(rf"\b{re.escape(key)}", low)
        )
        if hit and deal.company_id not in seen:
            seen.add(deal.company_id)
            out.append({"deal_id": deal.id, "lead_code": deal.lead_code, "company": name, "owner": deal.owner,
                        "status": deal.status, "key": key})
    return out


def _iso_or_none(value: Any, not_before: date | None = None) -> str | None:
    try:
        d = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
    if not_before and d < not_before:
        return None
    return d.isoformat()


def _item_date(item: dict) -> date:
    occurred = item.get("occurred_at")
    if isinstance(occurred, date):
        return occurred
    try:
        return date.fromisoformat(str(occurred)[:10])
    except (TypeError, ValueError):
        return get_settings().today()


# ---------------------------------------------------------------- nodes

def check_exclusions(state: CaptureState, config: RunnableConfig) -> CaptureState:
    item = state["item"]
    rules = _db(config).scalars(select(ExclusionRule)).all()
    emails = {p["email"].lower() for p in item.get("participants", []) if p.get("email")}
    domains = {email_domain(e) for e in emails}
    subject = (item.get("subject") or "").lower()
    body = (item.get("body") or "").lower()
    for r in rules:
        v = r.value.lower().strip()
        hit = (
            (r.rule_type == "email" and v in emails)
            or (r.rule_type == "domain" and v.lstrip("@") in domains)
            or (r.rule_type == "subject" and v in subject)
            or (r.rule_type == "keyword" and v in body)
        )
        if hit:
            return {
                "skipped": True,
                "skip_reason": f"Excluded by {r.rule_type} rule '{r.value}'",
                "trace": _trace(state, f"excluded: {r.rule_type}={r.value}"),
            }
    return {"skipped": False, "trace": _trace(state, "exclusions: none matched")}


def mask(state: CaptureState) -> CaptureState:
    masked, counts = mask_sensitive(state["item"].get("body") or "")
    return {"masked_body": masked, "masked_counts": counts, "trace": _trace(state, f"masked: {counts or 'nothing'}")}


def classify(state: CaptureState, config: RunnableConfig) -> CaptureState:
    s = get_settings()
    item = state["item"]
    db = _db(config)
    ext = _external_emails(item)
    pre = find_matches(db, company=None, emails=ext) if ext else []
    all_internal = not ext
    mentioned = _mentioned_deals(db, state["masked_body"]) if all_internal else []
    crm_hint = (
        "; ".join(f"{m['lead_code']} {m['company']} (status {m['status']})" for m in pre[:3]) or "no CRM record found"
    )
    if s.capture_llm_enabled:
        from .llm import classify_chain, prompt_constants

        result = classify_chain().invoke(
            {
                "conversation": _conversation_text(item, state["masked_body"]),
                "crm_hint": crm_hint,
                "mentioned": "; ".join(f"{m['lead_code']} {m['company']}" for m in mentioned) or "none",
                "internal_domain": prompt_constants()["internal_domain"],
            }
        ).model_dump()
        result["confidence"] = min(1.0, max(0.0, float(result["confidence"])))
        mode = "llm"
    else:
        result = heuristics.classify({**item, "body": state["masked_body"]}, bool(pre), all_internal, len(mentioned))
        mode = "rules"

    skip = result["category"] == "not_sales" and result["confidence"] >= 0.6
    if result["category"] == "internal_multi_deal" and not mentioned:
        # a client email is never a multi-deal internal note; fall back to the normal path
        result["category"] = "existing_deal" if pre else ("not_sales" if all_internal else "new_lead")
    out: CaptureState = {
        "classification": result,
        "pre_matches": pre,
        "mentioned": mentioned,
        "llm_mode": mode,
        "trace": _trace(state, f"classified: {result['category']} ({result['confidence']:.2f}) via {mode}"),
    }
    if skip:
        out.update(skipped=True, skip_reason=f"Not sales-related: {result['reason']}")
    return out


def extract(state: CaptureState, config: RunnableConfig) -> CaptureState:
    s = get_settings()
    item = state["item"]
    pre = state.get("pre_matches") or []
    crm_context = "none"
    if pre:
        deal = _db(config).get(Deal, pre[0]["deal_id"])
        if deal:
            crm_context = (
                f"{deal.lead_code} | {pre[0]['company']} | contact {pre[0]['contact']} | status {deal.status} | "
                f"service {deal.service_interest} | owner {deal.owner} | last contact {deal.last_contact_date} | "
                f"next step {deal.next_step or deal.next_followup_date} | notes: {deal.notes}"
            )
    if s.capture_llm_enabled:
        from .llm import extract_chain, prompt_constants

        result = extract_chain().invoke(
            {
                **prompt_constants(),
                "conversation": _conversation_text(item, state["masked_body"]),
                "today": s.today().isoformat(),
                "item_date": str(item.get("occurred_at") or "unknown"),
                "crm_context": crm_context,
            }
        ).model_dump()
        for key in ("summary", "followups", "new_needs"):
            result[key] = result.get(key) or []
        for val in result.values():
            if isinstance(val, dict) and "confidence" in val:
                val["confidence"] = min(1.0, max(0.0, float(val["confidence"] or 0)))
    else:
        result = heuristics.extract(
            {**item, "body": state["masked_body"]}, pre[0] if pre else None, s.today(), s.internal_domain
        )
    return {"extraction": result, "crm_context": crm_context, "trace": _trace(state, "extracted fields")}


def ground(state: CaptureState) -> CaptureState:
    source = _conversation_text(state["item"], state["masked_body"])
    crm = state.get("crm_context") or ""
    cleaned, dropped = ground_extraction(state["extraction"], source, "" if crm == "none" else crm)
    return {
        "extraction": cleaned,
        "dropped_fields": dropped,
        "trace": _trace(state, f"grounding: dropped {dropped or 'none'}"),
    }


def dates(state: CaptureState) -> CaptureState:
    """#2 Revisit-date detector: a focused pass for future time references the extraction may miss
    ("check back around Q2", "decision deferred to the 14 July board"). Evidence-checked like every field."""
    s = get_settings()
    item = state["item"]
    convo_date = _item_date(item)
    source = _conversation_text(item, state["masked_body"])
    if s.capture_llm_enabled:
        from .llm import dates_chain

        result = dates_chain().invoke({
            "conversation": source, "today": s.today().isoformat(), "item_date": convo_date.isoformat(),
        })
        signals = [x.model_dump() for x in (result.signals or [])]
    else:
        signals = heuristics.date_signals(state["masked_body"], convo_date)
    kept = []
    for sig in signals:
        resolved = _iso_or_none(sig.get("resolved_date"), not_before=convo_date)
        if resolved and evidence_in_source(sig.get("evidence"), source):
            kept.append({**sig, "resolved_date": resolved})
    found = [(x["kind"], x["resolved_date"]) for x in kept] or "none"
    return {"date_signals": kept, "trace": _trace(state, f"dates: {found}")}


def multi_extract(state: CaptureState, config: RunnableConfig) -> CaptureState:
    """#1 An internal note about several deals becomes one small update draft per deal it mentions."""
    s = get_settings()
    db = _db(config)
    item = state["item"]
    convo_date = _item_date(item)
    source = _conversation_text(item, state["masked_body"])
    mentioned = state.get("mentioned") or []
    if s.capture_llm_enabled:
        from .llm import multi_chain

        result = multi_chain().invoke({
            "conversation": source, "today": s.today().isoformat(), "item_date": convo_date.isoformat(),
            "deals": "; ".join(f"{m['lead_code']} {m['company']}" for m in mentioned) or "none listed",
        })
        raw = [x.model_dump() for x in (result.deals or [])]
    else:
        raw = heuristics.multi_deal(state["masked_body"], mentioned, convo_date)

    updates, used = [], set()
    by_code = {m["lead_code"]: m for m in mentioned}
    for r in raw:
        if not evidence_in_source(r.get("evidence"), source):
            continue
        target = by_code.get(r.get("lead_code") or "")
        if not target:
            cands = find_matches(db, company=r.get("company"), emails=[])
            best = next((c for c in cands if c["score"] >= 0.85), None)
            if best:
                target = {"deal_id": best["deal_id"], "lead_code": best["lead_code"],
                          "company": best["company"], "owner": best["owner"]}
        if target and target["deal_id"] in used:
            continue  # one draft per deal
        when = _iso_or_none(r.get("next_step_date"), not_before=convo_date)
        ev = r.get("evidence")
        fields = {
            "next_step": {"value": r.get("next_step"), "evidence": ev if r.get("next_step") else None,
                          "confidence": 0.7 if r.get("next_step") else 0.0},
            "next_step_date": {"value": when, "evidence": ev if when else None, "confidence": 0.7 if when else 0.0},
        }
        followups = []
        if when:
            followups.append({"reason": r.get("next_step") or r["update"], "due_date": when,
                              "suggested_next_step": r.get("next_step") or "Follow up", "owner_is_atliq": True,
                              "evidence": ev, "kind": "commitment"})
        if target:
            used.add(target["deal_id"])
            updates.append({
                "kind": "update", "category": "existing_deal", "deal_id": target["deal_id"],
                "owner": target.get("owner") or state.get("ingested_by"), "fields": fields,
                "summary": f"From internal note: {r['update']}", "followups": followups,
                "confidence": 0.7 if r.get("next_step") else 0.5, "needs_review": True,
                "missing_fields": [] if r.get("next_step") else ["next_step"],
                "matches": [{"deal_id": target["deal_id"], "lead_code": target["lead_code"], "company": target["company"],
                             "contact": None, "status": None, "owner": target.get("owner"), "service_interest": None,
                             "score": 1.0, "reasons": ["named in the internal note"]}],
            })
        else:  # a company the CRM doesn't know yet: suggest it as a new lead, for review
            fields["company"] = {"value": r.get("company"), "evidence": ev, "confidence": 0.6}
            fields["requirement"] = {"value": r["update"], "evidence": ev, "confidence": 0.5}
            updates.append({
                "kind": "new_lead", "category": "new_lead", "deal_id": None, "owner": state.get("ingested_by"),
                "fields": fields, "summary": f"From internal note: {r['update']}", "followups": followups,
                "confidence": 0.4, "needs_review": True, "missing_fields": ["contact_name"], "matches": [],
            })
    return {"multi_updates": updates,
            "trace": _trace(state, f"multi-deal note: {len(updates)} update(s) from {len(raw)} mention(s)")}


def match(state: CaptureState, config: RunnableConfig) -> CaptureState:
    ex = state["extraction"]
    emails = _external_emails(state["item"])
    if ex["contact_email"].get("value"):
        emails.append(ex["contact_email"]["value"])
    company = ex["company"].get("value")
    db = _db(config)
    matches = find_matches(db, company=company, emails=emails, contact_name=ex["contact_name"].get("value"))
    if company:
        # Referral guard: an intro sent BY an existing client's contact is about a different company
        # (e.g. FinEdge's Suresh introducing Harbor & Finch). Email-only matches must agree on company.
        matches = [m for m in matches if company_similarity(company, m["company"]) >= 0.5]

    # Notes that cite exactly one CRM id ("the Meridian deal (L-1003)") match it directly.
    codes = set(LEAD_CODE_RE.findall(state["masked_body"]))
    if len(codes) == 1:
        code = codes.pop()
        deal = db.scalar(select(Deal).where(Deal.lead_code == code))
        if deal and company and deal.company and company_similarity(company, deal.company.name) < 0.5:
            deal = None  # cited in passing (e.g. a QBR mentioning the referral's CRM id)
        if deal and not any(m["lead_code"] == code for m in matches):
            matches.insert(0, {
                "deal_id": deal.id, "lead_code": code, "company": deal.company.name if deal.company else None,
                "contact": deal.contact.name if deal.contact else None, "status": deal.status, "owner": deal.owner,
                "service_interest": deal.service_interest, "score": 1.0, "reasons": [f"conversation cites {code}"],
            })
        elif deal:
            for m in matches:
                if m["lead_code"] == code:
                    m["score"] = 1.0
                    m["reasons"].append(f"conversation cites {code}")
            matches.sort(key=lambda m: -m["score"])
    return {"matches": matches, "trace": _trace(state, f"matched: {[m['lead_code'] for m in matches] or 'none'}")}


def _pick_primary(matches: list[dict], service: str | None) -> dict | None:
    if not matches:
        return None
    top = matches[0]["score"]
    tied = [m for m in matches if m["score"] >= top - 0.02]
    if service:
        for m in tied:
            if m["service_interest"] == service and m["status"] not in CLOSED_STATUSES:
                return m
    open_ = [m for m in tied if m["status"] not in CLOSED_STATUSES]
    return (open_ or tied)[0]


def assess(state: CaptureState, config: RunnableConfig) -> CaptureState:
    s = get_settings()
    item = state["item"]
    ex = state["extraction"]
    cls = state["classification"]
    matches = state.get("matches") or []
    primary = _pick_primary(matches, ex["service_interest"].get("value"))

    if primary:
        kind = "update"
        category = "existing_client" if primary["status"] == "Won" else "existing_deal"
    else:
        kind = "new_lead"
        category = "new_lead"

    key_fields = KEY_FIELDS_UPDATE if kind == "update" else KEY_FIELDS_NEW
    missing = [f for f in key_fields if not ex.get(f, {}).get("value")]
    field_conf = [ex[f]["confidence"] for f in key_fields if ex.get(f, {}).get("value")]
    avg = (sum(field_conf) / len(key_fields)) if key_fields else 0.0
    confidence = round(avg * cls["confidence"], 2)

    # Owner: AtliQ seller on the thread, else existing deal owner, else whoever captured it.
    domain = s.internal_domain
    sellers = {n.lower(): n for n in s.seller_list}
    owner = None
    for p in item.get("participants", []):
        name = (p.get("name") or "").split()[0].lower() if p.get("name") else ""
        email_user = (p.get("email") or "").split("@")[0].lower()
        if (p.get("email") and is_internal(p["email"], domain)) or not p.get("email"):
            if email_user in sellers or name in sellers:
                owner = sellers.get(email_user) or sellers.get(name)
                break
    owner = owner or (primary or {}).get("owner") or state.get("ingested_by")

    # Deterministic follow-up signals on top of the model's.
    followups = list(ex.get("followups", []))
    last_sender = item.get("last_sender_email")
    occurred = item.get("occurred_at")
    if item.get("channel") == "email" and last_sender and not is_internal(last_sender, domain) and occurred:
        occurred_d = occurred if isinstance(occurred, date) else date.fromisoformat(str(occurred))
        followups.append(
            {
                "reason": "Client's last message has no AtliQ reply yet",
                "due_date": (occurred_d + timedelta(days=2)).isoformat(),
                "suggested_next_step": "Reply to the client's latest message",
                "owner_is_atliq": True,
                "evidence": f"Last message in thread is from {last_sender} on {occurred_d.isoformat()}",
                "deterministic": True,
            }
        )
    if ex["next_step_date"].get("value") and not any(
        f.get("due_date") == ex["next_step_date"]["value"] for f in followups
    ):
        followups.append(
            {
                "reason": f"Next step: {ex['next_step'].get('value') or 'follow up'}",
                "due_date": ex["next_step_date"]["value"],
                "suggested_next_step": ex["next_step"].get("value") or "Follow up with the client",
                "owner_is_atliq": True,
                "evidence": ex["next_step_date"].get("evidence"),
            }
        )

    # #2 date signals: add any dated item the extraction didn't already cover
    known = {f.get("due_date") for f in followups}
    labels = {"revisit": "Revisit", "deadline": "Deadline", "meeting": "Meeting", "decision": "Client decision",
              "other": "Date"}
    for sig in state.get("date_signals") or []:
        if sig["resolved_date"] in known:
            if sig["kind"] == "revisit":  # same date already listed: label it as a revisit
                for f in followups:
                    if f.get("due_date") == sig["resolved_date"]:
                        f["kind"] = "revisit"
            continue
        known.add(sig["resolved_date"])
        followups.append({
            "reason": f"{labels.get(sig['kind'], 'Date')}: {sig['what']}",
            "due_date": sig["resolved_date"],
            "suggested_next_step": sig["what"],
            "owner_is_atliq": True,
            "evidence": sig["evidence"],
            "kind": "revisit" if sig["kind"] == "revisit" else "commitment",
            "detector": "dates",
        })

    duplicates_in_crm = len([m for m in matches if m["score"] >= 0.9]) > 1
    needs_review = (
        confidence < s.confidence_threshold
        or bool(missing)
        or cls["category"] == "not_sales"  # low-confidence not-sales that we kept
        or duplicates_in_crm
        or bool(state.get("dropped_fields"))
    )
    return {
        "kind": kind,
        "category": category,
        "deal_id": primary["deal_id"] if primary else None,
        "owner": owner,
        "confidence": confidence,
        "missing_fields": missing,
        "needs_review": needs_review,
        "followups": followups,
        "trace": _trace(
            state, f"assessed: {kind} deal={primary['lead_code'] if primary else '-'} conf={confidence} review={needs_review}"
        ),
    }


def crosssell(state: CaptureState, config: RunnableConfig) -> CaptureState:
    """FR-11: ideas grounded ONLY in this client's own history (no cross-client leakage)."""
    s = get_settings()
    db = _db(config)
    deal = db.get(Deal, state["deal_id"])
    if not deal or not s.capture_llm_enabled:
        return {"crosssell": [], "trace": _trace(state, "cross-sell: skipped")}
    from .llm import crosssell_chain, prompt_constants

    company_deals = db.scalars(select(Deal).where(Deal.company_id == deal.company_id)).all()
    history = "\n".join(
        f"- {d.lead_code}: service {d.service_interest}, status {d.status}, notes: {d.notes or ''}" for d in company_deals
    )
    convo = _conversation_text(state["item"], state["masked_body"])
    result = crosssell_chain().invoke(
        {"catalogue": prompt_constants()["catalogue"], "history": history, "conversation": convo}
    )
    allowed = set(service_names())
    ideas = [
        i.model_dump()
        for i in (result.ideas or [])
        if i.service in allowed and evidence_in_source(i.evidence, convo + "\n" + history)
    ]
    return {"crosssell": ideas, "trace": _trace(state, f"cross-sell: {len(ideas)} idea(s)")}


# ---------------------------------------------------------------- routing

def _after_exclusions(state: CaptureState) -> str:
    return "end" if state.get("skipped") else "mask"


def _after_classify(state: CaptureState) -> str:
    if state.get("skipped"):
        return "end"
    return "multi" if state["classification"]["category"] == "internal_multi_deal" else "extract"


def _after_assess(state: CaptureState) -> str:
    return "crosssell" if state.get("category") == "existing_client" and state.get("deal_id") else "end"


def build_graph():
    g = StateGraph(CaptureState)
    g.add_node("check_exclusions", check_exclusions)
    g.add_node("mask", mask)
    g.add_node("classify", classify)
    g.add_node("extract", extract)
    g.add_node("ground", ground)
    g.add_node("dates", dates)
    g.add_node("multi_extract", multi_extract)
    g.add_node("match", match)
    g.add_node("assess", assess)
    g.add_node("crosssell", crosssell)

    g.add_edge(START, "check_exclusions")
    g.add_conditional_edges("check_exclusions", _after_exclusions, {"end": END, "mask": "mask"})
    g.add_edge("mask", "classify")
    g.add_conditional_edges("classify", _after_classify, {"end": END, "extract": "extract", "multi": "multi_extract"})
    g.add_edge("multi_extract", END)
    g.add_edge("extract", "ground")
    g.add_edge("ground", "dates")
    g.add_edge("dates", "match")
    g.add_edge("match", "assess")
    g.add_conditional_edges("assess", _after_assess, {"crosssell": "crosssell", "end": END})
    g.add_edge("crosssell", END)
    return g.compile()


_GRAPH = None


def run_capture(db: Session, item: dict, ingested_by: str) -> CaptureState:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH.invoke({"item": item, "ingested_by": ingested_by, "trace": []}, config={"configurable": {"db": db}})
