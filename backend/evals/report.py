"""Summarise results_<mode>.json into the AI PRD's eval metrics (section 11).

    python evals/report.py --golden "../../Dataset/golden" [--modes rules,llm]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--golden", required=True)
ap.add_argument("--modes", default="rules,llm")
args = ap.parse_args()
OUT = Path(args.golden).resolve() / "eval_results"


def pct(a, b):
    return None if not b else round(100 * a / b, 1)


def metrics(scored):
    run = [s for s in scored if not s.get("not_run")]
    m = {"run": len(run), "not_run": len(scored) - len(run)}
    tp = sum(s["exp_sales"] and s["pred_sales"] for s in run)
    fp = sum(not s["exp_sales"] and s["pred_sales"] for s in run)
    fn = sum(s["exp_sales"] and not s["pred_sales"] for s in run)
    m["sales_precision"] = pct(tp, tp + fp)
    m["sales_recall"] = pct(tp, tp + fn)
    m["category_accuracy"] = pct(sum(s["category_ok"] for s in run), len(run))
    mt = [s for s in run if "match_ok" in s]
    m["matching_accuracy"] = pct(sum(s["match_ok"] for s in mt), len(mt))
    m["wrong_merges"] = sum(bool(s.get("wrong_merge")) for s in mt)
    checks = [v for s in run for v in s.get("field_checks", {}).values()]
    m["field_accuracy"] = pct(sum(checks), len(checks))
    per_field = defaultdict(list)
    for s in run:
        for k, v in s.get("field_checks", {}).items():
            per_field[k].append(v)
    m["per_field"] = {k: pct(sum(v), len(v)) for k, v in per_field.items()}
    m["guessed_fields"] = sum(len(s.get("guessed_fields", [])) for s in run)
    hits = [h for s in run for h in s.get("followup_hits", [])]
    m["followup_recall"] = pct(sum(hits), len(hits))
    m["reminders_before_conversation"] = sum(s.get("reminders_before_conversation", 0) for s in run)
    cs = [s["crosssell_ok"] for s in run if "crosssell_ok" in s]
    m["crosssell_accuracy"] = pct(sum(cs), len(cs))
    mh = [h for s in run for h in s.get("multi_hits", [])]
    m["multi_deal_recall"] = pct(sum(mh), len(mh))
    m["leaked_secrets"] = sum(len(s.get("leaked_secrets", [])) for s in run)
    m["personal_stored"] = sum(bool(s.get("stored_personal")) for s in run)
    m["failed_items"] = sum(s["status"] == "failed" for s in run)
    by_diff = defaultdict(list)
    for s in run:
        by_diff[s["difficulty"]].append(s["category_ok"] and s.get("match_ok", True))
    m["by_difficulty"] = {k: pct(sum(v), len(v)) for k, v in by_diff.items()}
    return m


TARGETS = [
    ("Sales detection precision", "sales_precision", ">= 90%", lambda v: v is not None and v >= 90),
    ("Sales detection recall", "sales_recall", ">= 90%", lambda v: v is not None and v >= 90),
    ("Category accuracy", "category_accuracy", "(no PRD target)", None),
    ("CRM matching accuracy", "matching_accuracy", ">= 95%", lambda v: v is not None and v >= 95),
    ("Wrong merges", "wrong_merges", "0", lambda v: v == 0),
    ("Key field accuracy", "field_accuracy", ">= 90%", lambda v: v is not None and v >= 90),
    ("Guessed values where the answer is empty", "guessed_fields", "0", lambda v: v == 0),
    ("Follow-up date recall", "followup_recall", ">= 85%", lambda v: v is not None and v >= 85),
    ("Reminders dated before the conversation", "reminders_before_conversation", "0", lambda v: v == 0),
    ("Cross-sell accuracy (existing clients)", "crosssell_accuracy", "(no PRD target)", None),
    ("Internal notes: deals split out", "multi_deal_recall", "(no PRD target)", None),
    ("Secrets leaked (masking)", "leaked_secrets", "0", lambda v: v == 0),
    ("Personal items stored", "personal_stored", "0", lambda v: v == 0),
]

summary = {}
for mode in args.modes.split(","):
    f = OUT / f"results_{mode}.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        summary[mode] = {"meta": {k: data[k] for k in ("mode", "model", "run_at", "seconds")},
                         "metrics": metrics(data["scored"]), "scored": data["scored"]}

lines = ["# Golden set eval results", ""]
for mode, s in summary.items():
    meta, m = s["meta"], s["metrics"]
    lines.append(f"## {mode} mode" + (f" ({meta['model']})" if meta["model"] else ""))
    lines.append(f"Run {meta['run_at']}, {m['run']} conversations scored"
                 + (f", {m['not_run']} not run (provider limit)" if m["not_run"] else "")
                 + f", {meta['seconds']}s.")
    lines.append("")
    lines.append("| Metric | Result | Target | Pass |")
    lines.append("|---|---|---|---|")
    for label, key, target, ok in TARGETS:
        v = m[key]
        shown = "—" if v is None else (f"{v}%" if isinstance(v, float) else str(v))
        lines.append(f"| {label} | {shown} | {target} | {'' if ok is None else ('yes' if ok(v) else 'NO')} |")
    lines.append("")
    lines.append("Per field: " + ", ".join(f"{k} {v}%" for k, v in sorted(s["metrics"]["per_field"].items())))
    lines.append("")
    fails = [x for x in s["scored"] if not x.get("not_run") and (
        not x["category_ok"] or x.get("match_ok") is False or x.get("wrong_merge")
        or not all(x.get("followup_hits", [True])) or x.get("leaked_secrets"))]
    lines.append(f"Items with a category, match, follow-up or safety miss: {len(fails)}")
    lines.append("")
    lines.append("| ID | Expected | Got | Lead | Missed |")
    lines.append("|---|---|---|---|---|")
    for x in fails:
        miss = []
        if not x["category_ok"]:
            miss.append("category")
        if x.get("match_ok") is False:
            miss.append("match")
        if x.get("wrong_merge"):
            miss.append("WRONG MERGE")
        if not all(x.get("followup_hits", [True])):
            miss.append("follow-up date")
        if x.get("leaked_secrets"):
            miss.append("LEAKED SECRET")
        lines.append(f"| {x['id']} | {x['exp_category']} | {x['pred_category']} | {x.get('pred_lead') or ''} | "
                     f"{', '.join(miss)} |")
    lines.append("")
(OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps({k: {"meta": v["meta"], "metrics": v["metrics"]}
                                              for k, v in summary.items()}, indent=1), encoding="utf-8")
print("\n".join(lines))
