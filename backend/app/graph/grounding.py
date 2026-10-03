"""Groundedness guardrail: a field or sentence survives only if its evidence quote is really in the source.

PRD eval: 100% of saved fields traceable to a source message. Values whose evidence cannot be found are
emptied (missing values stay empty rather than guessed)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_WS = re.compile(r"[^a-z0-9@.$%]+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text.lower()).strip()


def evidence_in_source(evidence: str | None, source: str, min_ratio: float = 0.85) -> bool:
    if not evidence:
        return False
    ev, src = _norm(evidence), _norm(source)
    if not ev:
        return False
    if ev in src:
        return True
    # tolerate small paraphrase/punctuation drift: best fuzzy window over the source
    words, ev_len = src.split(), len(ev.split())
    if ev_len == 0 or not words:
        return False
    best = 0.0
    for i in range(0, max(1, len(words) - ev_len + 1)):
        window = " ".join(words[i: i + ev_len])
        best = max(best, SequenceMatcher(None, ev, window).ratio())
        if best >= min_ratio:
            return True
    return False


def ground_extraction(extraction: dict, source: str) -> tuple[dict, list[str]]:
    """Return a cleaned extraction and the list of fields dropped for lack of grounding."""
    dropped: list[str] = []
    out = dict(extraction)
    for key, val in extraction.items():
        if isinstance(val, dict) and "value" in val:
            if val.get("value") in (None, ""):
                out[key] = {"value": None, "evidence": None, "confidence": 0.0}
                continue
            if not evidence_in_source(val.get("evidence"), source):
                dropped.append(key)
                out[key] = {"value": None, "evidence": None, "confidence": 0.0, "dropped_value": val.get("value")}
            else:
                out[key] = {**val, "grounded": True}
    out["summary"] = [s for s in extraction.get("summary", []) if evidence_in_source(s.get("evidence"), source)]
    out["followups"] = [f for f in extraction.get("followups", []) if evidence_in_source(f.get("evidence"), source)]
    out["new_needs"] = [n for n in extraction.get("new_needs", []) if evidence_in_source(n.get("evidence"), source)]
    return out, dropped
