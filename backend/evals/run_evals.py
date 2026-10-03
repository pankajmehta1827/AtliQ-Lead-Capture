"""Offline eval of the capture pipeline against the labelled AtliQ dataset (PRD section: Evals).

Usage (from backend/):  python -m evals.run_evals            # uses GROQ_API_KEY if set, else rules mode
Runs on a throwaway SQLite DB seeded from crm_export.csv; nothing is written to the real database.

Reports:
- sales detection precision / recall          (PRD launch blocker: >= 90% / 90%)
- record matching accuracy and WRONG MERGES   (PRD: >= 95%, zero wrong merges)
- groundedness: fields dropped for lacking source evidence
- needs-review rate
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'atliq_eval.db'}"
os.environ.setdefault("REFERENCE_DATE", "2026-07-10")


def main() -> None:
    from app.db import Base, SessionLocal, engine
    from app.graph.pipeline import run_capture
    from app.models import Deal
    from app.parsing import parse_markdown_item
    from app.services.seed import import_crm_csv
    from app.config import get_settings

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    spec = json.loads((Path(__file__).parent / "labels.json").read_text())
    aliases, labels = spec["aliases"], spec["labels"]

    tp = fp = fn = tn = 0
    match_ok = wrong_merge = matched_total = 0
    dropped = needs_review = drafts = 0
    rows = []
    errors: list[tuple[str, str]] = []
    with SessionLocal() as db:
        import_crm_csv(db)
        codes = {d.id: d.lead_code for d in db.query(Deal).all()}
        limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
        for ref, expected in list(labels.items())[:limit]:
            path = ROOT / "data" / ref
            channel = "meeting" if ref.startswith("meeting") else "email"
            item = parse_markdown_item(path.read_text(encoding="utf-8"), ref, channel)
            try:
                for attempt in range(8):
                    try:
                        state = run_capture(db, item, "eval")
                        break
                    except Exception as exc:
                        if "rate limit" not in str(exc).lower() or attempt == 7:
                            raise
                        db.rollback()
                        print(f"  rate limited, waiting 30s ({ref})", flush=True)
                        time.sleep(30)
            except Exception as exc:  # count as a miss, keep evaluating
                db.rollback()
                errors.append((ref, f"{type(exc).__name__}: {str(exc)[:160]}"))
                rows.append((ref, expected, "ERROR", "MISS"))
                fn += expected != "not_sales"
                continue
            is_sales_pred = not state.get("skipped")
            is_sales_true = expected != "not_sales"
            tp += is_sales_pred and is_sales_true
            fp += is_sales_pred and not is_sales_true
            fn += (not is_sales_pred) and is_sales_true
            tn += (not is_sales_pred) and not is_sales_true
            got = "not_sales"
            if is_sales_pred:
                drafts += 1
                dropped += len(state.get("dropped_fields", []))
                needs_review += bool(state.get("needs_review"))
                got = codes.get(state.get("deal_id"), "new") if state.get("deal_id") else "new"
                got = aliases.get(got, got)
            if is_sales_true and is_sales_pred:
                matched_total += 1
                if got == expected:
                    match_ok += 1
                elif got != "new":
                    wrong_merge += 1  # attached to the WRONG existing record
            rows.append((ref, expected, got, "ok" if got == expected else "MISS"))

    def pct(a: int, b: int) -> str:
        return f"{100 * a / b:.1f}%" if b else "n/a"

    print(f"Mode: {'Groq ' + get_settings().groq_model if get_settings().llm_enabled else 'rules (no GROQ_API_KEY)'}")
    for r in rows:
        print(f"  {r[3]:4}  {r[0]:58} expected {r[1]:9} got {r[2]}")
    print("\nSales detection   precision", pct(tp, tp + fp), " recall", pct(tp, tp + fn), "(target >= 90% / 90%)")
    print("Record matching   accuracy ", pct(match_ok, matched_total), f" wrong merges: {wrong_merge} (target >= 95%, 0)")
    print(f"Groundedness      {dropped} field value(s) dropped for missing evidence across {drafts} drafts")
    print("Needs review rate", pct(needs_review, drafts))
    print(f"Errors            {len(errors)}")
    for ref, err in errors:
        print(f"  {ref}: {err}")


if __name__ == "__main__":
    main()
