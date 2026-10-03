"""Turn raw email threads / meeting notes (markdown, as in the AtliQ dataset or pasted by a user) into a
normalised capture item. Real mailbox/calendar connectors would produce the same shape."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

ADDR_RE = re.compile(r"([^<>,;]*?)\s*<([^<>\s]+@[^<>\s]+)>")
BARE_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# Dataset-only editorial notes like "*(No reply sent as of 2026-07-10.)*" are ground truth for
# evaluation, not part of the conversation, so they must never reach the model.
EDITORIAL_RE = re.compile(r"\*\([^)]*\)\*")
HEADER_RE = re.compile(r"^\*\*(From|To|Cc|Date|Subject|Attendees|Type|Duration):\*\*\s*(.*)$", re.I)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    m = ISO_DATE_RE.search(value)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _addresses(value: str) -> list[dict[str, str | None]]:
    found = [{"name": n.strip().strip('"') or None, "email": e.lower()} for n, e in ADDR_RE.findall(value)]
    if not found:
        found = [{"name": None, "email": e.lower()} for e in BARE_EMAIL_RE.findall(value)]
    return found


def strip_editorial(text: str) -> str:
    cleaned = EDITORIAL_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def parse_markdown_item(text: str, filename: str | None = None, channel_hint: str | None = None) -> dict[str, Any]:
    text = strip_editorial(text.replace("\r\n", "\n"))
    lines = text.split("\n")
    title = next((ln[2:].strip() for ln in lines if ln.startswith("# ")), None)

    channel = channel_hint
    if not channel:
        lowered = (filename or "").lower()
        if "meeting" in lowered or (title and title.lower().startswith(("meeting", "internal"))):
            channel = "meeting"
        elif "**From:**" in text:
            channel = "email"
        else:
            channel = "meeting"

    participants: list[dict[str, str | None]] = []
    messages: list[dict[str, Any]] = []  # per message in an email thread
    subject = None
    first_date: date | None = None
    attendees: list[str] = []

    current: dict[str, Any] | None = None
    for ln in lines:
        # meeting header lines look like "**Date:** 2026-07-09 · **Attendees:** a, b"
        for part in re.split(r"\s+·\s+", ln.strip()):
            m = HEADER_RE.match(part.strip())
            if not m:
                continue
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "from":
                current = {"from": _addresses(val), "date": None}
                messages.append(current)
                participants.extend(current["from"])
            elif key in ("to", "cc"):
                participants.extend(_addresses(val))
            elif key == "date":
                d = _parse_date(val)
                if current is not None and current.get("date") is None:
                    current["date"] = d
                first_date = first_date or d
            elif key == "subject" and not subject:
                subject = val
            elif key == "attendees":
                attendees = [a.strip() for a in re.split(r",|;", val) if a.strip()]

    if not first_date and filename:
        first_date = _parse_date(filename)

    # de-duplicate participants by email
    seen: set[str] = set()
    uniq: list[dict[str, str | None]] = []
    for p in participants:
        if p["email"] and p["email"] not in seen:
            seen.add(p["email"])
            uniq.append(p)
    for name in attendees:
        uniq.append({"name": name, "email": None})

    sender = messages[0]["from"][0] if messages and messages[0]["from"] else None
    last_sender = messages[-1]["from"][0] if messages and messages[-1]["from"] else None
    last_date = None
    for msg in messages:
        last_date = msg.get("date") or last_date

    return {
        "channel": channel,
        "external_ref": filename,
        "subject": subject or title,
        "title": title,
        "sender_name": sender["name"] if sender else None,
        "sender_email": sender["email"] if sender else None,
        "last_sender_email": last_sender["email"] if last_sender else None,
        "participants": uniq,
        "occurred_at": (last_date or first_date),
        "first_date": first_date,
        "body": text,
    }


def is_internal(email: str | None, internal_domain: str) -> bool:
    return bool(email) and email.lower().endswith("@" + internal_domain.lower())


def email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].lower()
