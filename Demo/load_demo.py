"""Load the demo conversations into a running AtliQ Lead Assistant, the same way the Add conversation page does.

    python Demo/load_demo.py --safety          # pre-load G-028 and G-038 before recording
    python Demo/load_demo.py --all             # load all five (rehearsal)
    python Demo/load_demo.py --sample          # also run "Sync sample mailbox & calendar" first

Defaults to http://localhost:8000 as user Jay. For another server pass --url; if it needs an access code,
set the ATLIQ_ACCESS_CODE environment variable (it is never printed).
Pasting the same text twice counts as the same conversation, so re-running this makes no duplicates.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = ["1_G-013_vertex_check_back_october.md", "2_G-025_internal_weekly_sales_sync.md",
        "3_G-021_northwind_eta_prediction.md"]
SAFETY = ["safety_G-028_personal_proposal_plans.md", "safety_G-038_shopswift_vendor_registration.md"]


def call(url: str, path: str, user: str, body: dict | None = None) -> dict:
    headers = {"X-User": user, "Content-Type": "application/json"}
    if os.environ.get("ATLIQ_ACCESS_CODE"):
        headers["X-Access-Code"] = os.environ["ATLIQ_ACCESS_CODE"]
    req = urllib.request.Request(url.rstrip("/") + path, method="POST", headers=headers,
                                 data=json.dumps(body or {}).encode())
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read() or b"{}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--user", default="Jay")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--safety", action="store_true", help="only the two safety items (default)")
    g.add_argument("--all", action="store_true", help="all five demo items")
    ap.add_argument("--sample", action="store_true", help="sync the sample mailbox first (needed for Ask AI A-010)")
    a = ap.parse_args()

    try:
        if a.sample:
            print("sample mailbox:", call(a.url, "/api/capture/sample", a.user))
        for name in (LIVE + SAFETY) if a.all else SAFETY:
            text = (HERE / name).read_text(encoding="utf-8")
            channel = "meeting" if "weekly_sales_sync" in name else "email"
            out = call(a.url, "/api/capture", a.user, {"channel": channel, "text": text})
            print(f"{name}: item {out['item']['id']} ({'new' if out['created'] else 'already captured'})")
        for _ in range(20):  # drain the queue (the background worker would also pick these up)
            done = call(a.url, "/api/capture/process?limit=50", a.user)
            print("process:", done)
            if not any(v for k, v in done.items() if k != "skipped"):
                break
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{e.code} {e.reason}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {a.url} ({e.reason}). Is the app running?")


if __name__ == "__main__":
    main()
