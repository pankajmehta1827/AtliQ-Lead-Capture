"""Capture queue: store incoming conversations, run the LangGraph pipeline, persist drafts.

Items are queued first so nothing is lost if the LLM / an integration is down (PRD state
'Integration unavailable': warn, queue for retry, log the gap)."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import log_action
from ..config import get_settings
from ..db import SessionLocal
from ..graph.pipeline import run_capture
from ..models import Draft, SourceItem

log = logging.getLogger("atliq.capture")


def enqueue_item(db: Session, parsed: dict[str, Any], ingested_by: str) -> tuple[SourceItem, bool]:
    """Returns (item, created). Re-ingesting the same external_ref is a no-op."""
    ref = parsed.get("external_ref")
    if ref:
        existing = db.scalar(select(SourceItem).where(SourceItem.external_ref == ref))
        if existing:
            return existing, False
    occurred = parsed.get("occurred_at")
    if isinstance(occurred, str):
        occurred = date.fromisoformat(occurred[:10]) if occurred else None
    item = SourceItem(
        channel=parsed.get("channel") or "email",
        external_ref=ref,
        subject=parsed.get("subject"),
        sender_name=parsed.get("sender_name"),
        sender_email=parsed.get("sender_email"),
        participants=parsed.get("participants") or [],
        occurred_at=occurred,
        body=parsed.get("body"),
        status="queued",
        ingested_by=ingested_by,
    )
    db.add(item)
    db.flush()
    log_action(
        db, actor=ingested_by, action="captured", outcome="queued", entity_type="source_item",
        entity_id=item.id, source_ref=ref or item.subject, details={"channel": item.channel},
    )
    db.commit()
    return item, True


def _item_dict(si: SourceItem) -> dict[str, Any]:
    from ..parsing import parse_markdown_item

    last_sender = None
    if si.body and "**From:**" in si.body:
        last_sender = parse_markdown_item(si.body, si.external_ref, si.channel).get("last_sender_email")
    title = None
    if si.body:
        title = next((ln[2:].strip() for ln in si.body.split("\n") if ln.startswith("# ")), None)
    return {
        "channel": si.channel,
        "external_ref": si.external_ref,
        "subject": si.subject,
        "title": title or si.subject,
        "sender_name": si.sender_name,
        "sender_email": si.sender_email,
        "last_sender_email": last_sender,
        "participants": si.participants or [],
        "occurred_at": si.occurred_at,
        "body": si.body or "",
    }


def _crosssell_ideas(state: dict) -> list[dict]:
    """Model ideas for existing clients; fall back to surfacing raw 'new needs' so they are not lost."""
    if state.get("category") != "existing_client":
        return []
    if state.get("crosssell"):
        return state["crosssell"]
    return [
        {"service": None, "rationale": f"New need mentioned: {n['need']}", "evidence": n["evidence"]}
        for n in state["extraction"].get("new_needs", [])
    ]


RATE_LIMIT_BACKOFF_SECONDS = 30
_backoff_until = 0.0


def _retry_after_seconds(message: str) -> float:
    """Groq says e.g. 'Please try again in 2m38.97s'. Wait that long (min 30s, max 1h)."""
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?", message)
    if not m or not any(m.groups()):
        return RATE_LIMIT_BACKOFF_SECONDS
    h, mi, sec = (float(g) if g else 0.0 for g in m.groups())
    return min(3600.0, max(RATE_LIMIT_BACKOFF_SECONDS, h * 3600 + mi * 60 + sec + 1))


def _is_rate_limit(exc: Exception) -> bool:
    return type(exc).__name__ == "RateLimitError" or "rate limit" in str(exc).lower()


def process_item(db: Session, item_id: int) -> str:
    s = get_settings()
    si = db.get(SourceItem, item_id)
    if not si or si.status not in ("queued",):
        return "noop"
    if not s.processing_enabled:
        return "paused"
    si.status = "processing"
    si.attempts += 1
    db.commit()

    try:
        state = run_capture(db, _item_dict(si), si.ingested_by or "assistant")
    except Exception as exc:  # LLM / network failure -> retry later, never drop silently
        db.rollback()
        si = db.get(SourceItem, item_id)
        si.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if _is_rate_limit(exc):
            # Provider quota, not a bad item: requeue without spending a retry and pause the worker.
            si.attempts -= 1
            si.status = "queued"
            global _backoff_until
            delay = _retry_after_seconds(str(exc))
            _backoff_until = time.monotonic() + delay
            db.commit()
            log.info("rate limited on item %s; backing off %.0fs", item_id, delay)
            return "rate_limited"
        si.status = "failed" if si.attempts >= s.max_retries else "queued"
        log_action(
            db, actor="assistant", action="processing_error", outcome=si.status, entity_type="source_item",
            entity_id=si.id, source_ref=si.external_ref or si.subject,
            details={"error": si.last_error, "attempt": si.attempts},
        )
        db.commit()
        log.warning("item %s failed (attempt %s): %s", item_id, si.attempts, exc)
        return si.status

    si.processed_at = datetime.now(timezone.utc)
    if state.get("skipped"):
        # Not sales-related / excluded: do not keep the content (PRD: "Do not process or store it").
        si.status = "skipped"
        si.skip_reason = state.get("skip_reason")
        si.category = (state.get("classification") or {}).get("category")
        si.body = None
        si.subject = None
        si.participants = []
        si.sender_name = None
        si.sender_email = None
        log_action(
            db, actor="assistant", action="skipped", outcome="skipped", entity_type="source_item",
            entity_id=si.id, source_ref=si.external_ref, details={"reason": si.skip_reason},
        )
        db.commit()
        return "skipped"

    # Store the masked body only.
    si.body = state.get("masked_body", si.body)
    si.category = state.get("category")
    si.status = "processed"

    if "multi_updates" in state:
        # #1 internal note about several deals: one small update draft per deal it mentions
        si.category = "internal_multi_deal"
        ids = []
        for u in state["multi_updates"]:
            d = Draft(
                source_item_id=si.id, kind=u["kind"], category=u["category"], deal_id=u["deal_id"],
                fields=u["fields"], summary=u["summary"], confidence=u["confidence"], needs_review=u["needs_review"],
                missing_fields=u["missing_fields"], duplicate_candidates=u["matches"], followups=u["followups"],
                crosssell=[], owner=u["owner"], llm_mode=state.get("llm_mode", "llm"),
            )
            db.add(d)
            db.flush()
            ids.append(d.id)
        log_action(
            db, actor="assistant", action="multi_deal_note", outcome=f"{len(ids)} draft(s)", entity_type="source_item",
            entity_id=si.id, source_ref=si.external_ref or si.subject,
            details={"draft_ids": ids, "trace": state.get("trace", [])},
        )
        db.commit()
        return "processed"

    ex = state["extraction"]
    draft = Draft(
        source_item_id=si.id,
        kind=state["kind"],
        category=state["category"],
        deal_id=state.get("deal_id"),
        fields={k: v for k, v in ex.items() if isinstance(v, dict) and "value" in v},
        summary=" ".join(x["text"] for x in ex.get("summary", [])) or None,
        confidence=state.get("confidence", 0.0),
        needs_review=state.get("needs_review", True),
        missing_fields=state.get("missing_fields", []),
        duplicate_candidates=state.get("matches", []),
        followups=state.get("followups", []),
        crosssell=_crosssell_ideas(state),
        owner=state.get("owner"),
        llm_mode=state.get("llm_mode", "llm"),
    )
    db.add(draft)
    db.flush()
    log_action(
        db, actor="assistant", action="draft_created", outcome="needs_review" if draft.needs_review else "ready",
        entity_type="draft", entity_id=draft.id, source_ref=si.external_ref or si.subject,
        details={
            "kind": draft.kind, "category": draft.category, "deal_id": draft.deal_id,
            "confidence": draft.confidence, "dropped_fields": state.get("dropped_fields", []),
            "masked": state.get("masked_counts", {}), "trace": state.get("trace", []),
        },
    )
    db.commit()
    return "processed"


def process_pending(db: Session, limit: int = 20) -> dict[str, int]:
    ids = db.scalars(
        select(SourceItem.id).where(SourceItem.status == "queued").order_by(SourceItem.id).limit(limit)
    ).all()
    counts: dict[str, int] = {}
    for item_id in ids:
        outcome = process_item(db, item_id)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome == "rate_limited":
            break
    return counts


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def worker_loop(stop: asyncio.Event) -> None:
    s = get_settings()

    def _run() -> dict[str, int]:
        with SessionLocal() as db:
            return process_pending(db, limit=5)

    while not stop.is_set():
        wait = _backoff_until - time.monotonic()
        if wait > 0:
            await _sleep(stop, wait)
            continue
        try:
            counts = await asyncio.to_thread(_run)
            if counts and "rate_limited" not in counts:
                log.info("worker processed %s", counts)
                continue  # more may be waiting
        except Exception:  # pragma: no cover - keep the worker alive
            log.exception("worker loop error")
        await _sleep(stop, s.worker_poll_seconds)
