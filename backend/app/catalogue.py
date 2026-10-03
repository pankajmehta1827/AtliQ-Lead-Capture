from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SOURCES = ["Referral", "LinkedIn", "Conference", "Website", "Cold Outreach", "Existing Client", "Partner"]
STAGES = ["New", "Contacted", "Proposal Sent", "Won", "Lost"]


@lru_cache
def load_catalogue() -> list[dict]:
    return json.loads((DATA_DIR / "service_catalogue.json").read_text(encoding="utf-8"))["services"]


def service_names() -> list[str]:
    return [s["name"] for s in load_catalogue()]


def catalogue_text() -> str:
    return "\n".join(f"- {s['name']}: {', '.join(s['typical_needs'])}" for s in load_catalogue())
