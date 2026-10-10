"""Score the capture pipeline against the golden set (Dataset/golden).

Each golden conversation goes through the production path: parse -> queue -> process_item, against a throwaway SQLite
copy of the CRM, so the live database is never touched.

    python evals/run_golden.py --golden "../../Dataset/golden" --mode rules
    python evals/run_golden.py --golden "../../Dataset/golden" --mode llm      # uses the GROQ_API_KEY in backend/.env

Writes results_<mode>.json next to the golden set (in eval_results/).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

ap = argparse.ArgumentParser()
ap.add_argument("--golden", required=True)
ap.add_argument("--mode", choices=["rules", "llm"], default="rules")
ap.add_argument("--limit", type=int, default=None)
ap.add_argument("--ids", default="", help="comma-separated golden ids to run")
ap.add_argument("--resume", action="store_true", help="keep finished items from an earlier run of this mode")
args = ap.parse_args()

db_file = Path(tempfile.gettempdir()) / f"atliq_golden_{args.mode}.db"
db_file.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
os.environ["REFERENCE_DATE"] = "2026-07-10"
os.environ["SEED_ON_STARTUP"] = "false"
os.environ["PROCESSING_ENABLED"] = "true"
if args.mode == "rules":
    os.environ["GROQ_API_KEY"] = ""

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Deal, Draft, SourceItem  # noqa: E402
from app.parsing import parse_markdown_item  # noqa: E402
from app.services import capture  # noqa: E402
from app.services.capture import enqueue_item, process_item  # noqa: E402
from app.services.seed import import_crm_csv  # noqa: E402

GOLDEN = Path(args.golden).resolve()
OUT = GOLDEN / "eval_results"
OUT.mkdir(exist_ok=True)
settings = get_settings()
if args.mode == "llm" and not settings.llm_enabled:
    sys.exit("No GROQ_API_KEY configured: cannot run --mode llm")

Base.metadata.create_all(engine)
db = SessionLocal()
import_crm_csv(db)
db.commit()
lead_of = {d.id: d.lead_code for d in db.scalars(select(Deal))}

labels = [json.loads(line) for line in (GOLDEN / "golden_labels.jsonl").read_text(encoding="utf-8").splitlines()]
if args.ids:
    wanted = set(args.ids.split(","))
    labels = [x for x in labels if x["id"] in wanted]
labels = labels[: args.limit]
CHANNEL = {"emails": "email", "meeting_notes": "meeting", "linkedin": "linkedin"}


def run_one(lab: dict) -> dict:
    path = GOLDEN / lab["file"]
    channel = CHANNEL[path.parent.name]
    parsed = parse_markdown_item(path.read_text(encoding="utf-8"), f"golden/{lab['file']}", channel)
    si, _ = enqueue_item(db, parsed, "eval")
    db.commit()
    for attempt in range(6):
        capture._backoff_until = 0.0
        outcome = process_item(db, si.id)
        if outcome != "rate_limited":
            break
        db.refresh(si)
        wait = min(capture._retry_after_seconds(si.last_error or ""), 900)
        if wait > 120:
            return {"id": lab["id"], "status": "not_run", "reason": f"rate limit, retry in {int(wait)}s"}
        time.sleep(wait + 2)
    db.refresh(si)
    drafts = db.scalars(select(Draft).where(Draft.source_item_id == si.id)).all()
    return {
        "id": lab["id"], "status": si.status, "outcome": outcome, "error": si.last_error,
        "stored_body": si.body,
        "drafts": [{
            "kind": d.kind, "category": d.category, "lead": lead_of.get(d.deal_id),
            "fields": {k: (v or {}).get("value") for k, v in (d.fields or {}).items()},
            "followups": [f.get("due_date") for f in d.followups or []],
            "crosssell": [c.get("service") for c in d.crosssell or [] if c.get("service")],
            "duplicates": [c.get("lead_code") for c in d.duplicate_candidates or []],
            "needs_review": d.needs_review, "summary": d.summary, "raw": json.dumps(
                {"f": d.fields, "s": d.summary, "fu": d.followups, "cs": d.crosssell}, ensure_ascii=False),
        } for d in drafts],
    }


# ---------------------------------------------------------------- scoring
def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def money(s):
    """'$20k' / '20000' / '$8k per engineer' / 'INR 3 lakh' -> comparable number, or None."""
    t = str(s or "").lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k|lakh|lac|l\b|m\b)?", t)
    if not m:
        return None
    v = float(m.group(1)) * {"k": 1e3, "lakh": 1e5, "lac": 1e5, "l": 1e5, "m": 1e6}.get(m.group(2) or "", 1)
    return v


def field_ok(name, exp, got, lab):
    if name == "requirement_keywords":
        hits = sum(norm(k) in norm(got) for k in exp)
        return hits >= max(1, len(exp) // 2)
    if name == "next_step":
        return bool(got)  # wording varies; a next step must be captured
    if name == "next_step_date":
        return got in (lab["expected"].get("acceptable_dates") or [exp])
    if name == "budget":
        a, b = money(exp), money(got)
        return a is not None and b is not None and abs(a - b) <= 0.05 * a
    if name in ("company", "contact_name"):
        return bool(got) and (norm(exp) in norm(got) or norm(got) in norm(exp))
    if name == "stage" and exp == "New" and not got and lab["expected"]["category"] == "new_lead":
        return True  # new leads are saved with stage New on Confirm
    if name == "source" and lab["id"] == "G-005":
        return got in ("Conference", "Referral")
    return norm(exp) == norm(got)


def score(lab: dict, res: dict) -> dict:
    e = lab["expected"]
    r = {"id": lab["id"], "difficulty": lab["difficulty"], "scenario": lab["scenario"],
         "exp_category": e["category"], "status": res["status"]}
    if res["status"] == "not_run":
        r["not_run"] = True
        return r
    drafts = res["drafts"]
    main = drafts[0] if drafts else None
    pred_sales = res["status"] != "skipped" and bool(drafts)
    if res["status"] == "failed":
        r["error"] = res.get("error")
    pred_cat = "not_sales" if not pred_sales else (
        "internal_multi_deal" if any(d["category"] == "internal_multi_deal" for d in drafts) or len(drafts) > 1
        else main["category"])
    r.update(exp_sales=e["is_sales"], pred_sales=pred_sales, pred_category=pred_cat,
             category_ok=pred_cat == e["category"] or pred_cat in e.get("acceptable_categories", []))

    # matching
    ok_leads = {e.get("match_lead_id"), *e.get("also_acceptable", [])} - {None}
    if e["category"] in ("existing_deal", "existing_client") and main:
        r["pred_lead"] = main["lead"]
        r["match_ok"] = main["lead"] in ok_leads
        r["wrong_merge"] = main["lead"] is not None and main["lead"] not in ok_leads
    elif e["category"] == "new_lead" and main:
        r["pred_lead"] = main["lead"]
        r["match_ok"] = main["kind"] == "new_lead" and main["lead"] is None
        r["wrong_merge"] = main["lead"] is not None
    if main and e.get("must_not_match"):
        r["must_not_match_hit"] = any(d["lead"] in e["must_not_match"] for d in drafts)
        r["wrong_merge"] = r.get("wrong_merge") or r["must_not_match_hit"]
    if e.get("duplicate_candidates") and main:
        r["duplicates_flagged"] = set(e["duplicate_candidates"]) <= set(main["duplicates"] + [main["lead"]])

    # fields (only for single-conversation items with a draft)
    if main and e["category"] in ("new_lead", "existing_deal", "existing_client"):
        checks, guesses = {}, []
        for name, exp in e["fields"].items():
            got = main["fields"].get("requirement" if name == "requirement_keywords" else name)
            if exp is None:
                if got and name in ("contact_email", "contact_name", "budget", "next_step_date") \
                        and e["category"] == "new_lead":
                    guesses.append(name)
                continue
            if name in ("company", "contact_name") and e["category"] != "new_lead":
                continue  # updates are matched to the CRM record; name fields are not re-entered
            checks[name] = field_ok(name, exp, got, lab)
        r["field_checks"] = checks
        r["guessed_fields"] = guesses

    # follow-ups: an expected date counts if any reminder or the next-step date carries it
    if e.get("followups") and main:
        got_dates = {d for dr in drafts for d in dr["followups"]} | {dr["fields"].get("next_step_date") for dr in drafts}
        acc = set(e.get("acceptable_dates", []))
        r["followup_hits"] = [fu["due_date"] in got_dates or bool(acc & got_dates) for fu in e["followups"]]
    if main:
        conv = date.fromisoformat(lab["date"])
        r["reminders_before_conversation"] = sum(
            1 for dr in drafts for d in dr["followups"] if d and date.fromisoformat(d[:10]) < conv)

    # cross-sell
    if e["category"] == "existing_client" and main:
        got = set(main["crosssell"])
        r["crosssell_ok"] = set(e["crosssell"]) <= got if e["crosssell"] else not got

    # multi-deal notes
    if e.get("multi_deal_updates"):
        got_leads = {d["lead"] for d in drafts}
        new_cos = {norm(d["fields"].get("company")) for d in drafts if d["kind"] == "new_lead"}
        hits = []
        for u in e["multi_deal_updates"]:
            if u.get("lead_id"):
                hits.append(u["lead_id"] in got_leads)
            else:
                hits.append(any(norm(u["company"]).split()[0] in c for c in new_cos if c))
        r["multi_hits"] = hits

    # safety
    if e.get("must_be_masked"):
        blob = " ".join(d["raw"] for d in drafts) + " " + (res.get("stored_body") or "")
        r["leaked_secrets"] = [s for s in e["must_be_masked"] if s in blob]
    if e.get("must_not_store"):
        r["stored_personal"] = bool(res.get("stored_body")) or bool(drafts)
    return r


results, scored = [], []
start = time.time()
done = {}
prev = OUT / f"results_{args.mode}.json"
if args.resume and prev.exists():
    done = {r["id"]: r for r in json.loads(prev.read_text(encoding="utf-8"))["raw"] if r["status"] != "not_run"}
    print(f"resuming: {len(done)} finished items kept", flush=True)
for i, lab in enumerate(labels, 1):
    res = done.get(lab["id"]) or run_one(lab)
    results.append(res)
    scored.append(score(lab, res))
    print(f"[{i}/{len(labels)}] {lab['id']} {res['status']}", flush=True)
    if res["status"] == "not_run":
        for rest in labels[i:]:
            results.append({"id": rest["id"], "status": "not_run", "reason": "stopped after rate limit"})
            scored.append(score(rest, results[-1]))
        print("Stopped: provider daily limit reached.", flush=True)
        break

out = {"mode": args.mode, "model": settings.groq_model if args.mode == "llm" else None,
       "run_at": datetime.now().isoformat(timespec="seconds"), "seconds": round(time.time() - start),
       "scored": scored, "raw": results}
(OUT / f"results_{args.mode}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
print("wrote", OUT / f"results_{args.mode}.json")
