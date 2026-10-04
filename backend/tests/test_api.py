def test_seed_and_dashboard(client):
    deals = client.get("/api/deals").json()
    assert len(deals) > 20  # open deals from crm_export.csv
    # flagged deals come first
    assert deals[0]["flags"]
    finedge = next(d for d in deals if d["lead_code"] == "L-1023")
    assert "proposal_unanswered" in finedge["flags"] and "inactive" in finedge["flags"]


def test_auth_required(client):
    assert client.get("/api/deals", headers={"X-User": "Mallory"}).status_code == 401


def test_full_capture_review_flow(client):
    r = client.post("/api/capture/sample", params={"limit": 40})
    assert r.json()["queued"] == 40
    # idempotent
    assert client.post("/api/capture/sample", params={"limit": 40}).json()["queued"] == 0

    for _ in range(5):
        client.post("/api/capture/process", params={"limit": 50})
    items = client.get("/api/capture/items").json()
    assert items["counts"].get("queued", 0) == 0
    assert items["counts"].get("processed", 0) > 0

    # Nothing is written to the CRM before confirmation
    assert len(client.get("/api/deals", params={"open_only": False}).json()) == 40

    drafts = client.get("/api/drafts").json()
    assert drafts
    # existing contact email -> proposes update, not a duplicate (FinEdge)
    finedge = [d for d in drafts if d["source"]["external_ref"].endswith("finedge_compliance_docs.md")]
    assert finedge and finedge[0]["kind"] == "update" and finedge[0]["deal_lead_code"] == "L-1023"

    # PixelWorks is missing from the CRM -> new lead draft
    pixel = next(d for d in drafts if "pixelworks" in d["source"]["external_ref"])
    assert pixel["kind"] == "new_lead"
    res = client.post(
        f"/api/drafts/{pixel['id']}/confirm",
        json={"edits": {"company": "PixelWorks Agency", "source": "Partner", "next_step": "Reply to Tara",
                        "next_step_date": "2026-07-12"}},
    )
    assert res.status_code == 200, res.text
    deal = res.json()["deal"]
    assert deal["company"] == "PixelWorks Agency" and deal["lead_code"] == "L-1041"
    assert len(client.get("/api/deals", params={"open_only": False}).json()) == 41
    # reminder created from the owner's next-step date
    rems = client.get("/api/reminders").json()
    assert any(r["deal_id"] == deal["id"] and r["due_date"] == "2026-07-12" for r in rems)
    # second confirm is rejected
    assert client.post(f"/api/drafts/{pixel['id']}/confirm", json={}).status_code == 409

    # discard is logged
    other = next(d for d in drafts if d["id"] != pixel["id"])
    assert client.post(f"/api/drafts/{other['id']}/discard", json={"reason": "test"}).status_code == 200
    actions = {a["action"] for a in client.get("/api/audit").json()}
    assert {"captured", "draft_created", "draft_confirmed", "draft_discarded"} <= actions

    m = client.get("/api/metrics").json()
    assert m["trust"]["reviewed"] == 2


def test_exclusion_rule_skips_and_wipes_content(client):
    client.post("/api/exclusions", json={"rule_type": "domain", "value": "pixelworks.agency"})
    client.post("/api/capture/sample", params={"limit": 34})
    client.post("/api/capture/process", params={"limit": 50})
    items = client.get("/api/capture/items", params={"status": "skipped"}).json()["items"]
    px = next(i for i in items if "pixelworks" in (i["external_ref"] or ""))
    assert px["subject"] is None and px["sender_email"] is None
    assert "Excluded" in px["skip_reason"]


def test_manual_capture_masks_secrets(client):
    r = client.post("/api/capture", json={
        "channel": "linkedin",
        "text": "Hi Jay, we need a Power BI dashboard for our 4 warehouses. Budget 30k. "
                "Our card is 4111 1111 1111 1111. Can you send a proposal by 20 Jul?",
        "contact_name": "Lena Ortiz", "contact_email": "lena@stackwave.io", "subject": "StackWave dashboards",
    })
    assert r.status_code == 200
    client.post("/api/capture/process")
    d = next(x for x in client.get("/api/drafts").json() if x["source"]["subject"] == "StackWave dashboards")
    body = client.get(f"/api/drafts/{d['id']}").json()["source"]["body"]
    assert "4111" not in body and "[MASKED_CARD]" in body
    assert any(f["due_date"] == "2026-07-20" for f in d["followups"])


def test_reminder_scan_and_summary(client):
    assert client.post("/api/reminders/scan").json()["created"] > 0
    assert client.post("/api/reminders/scan").json()["created"] == 0  # deduplicated
    summary = client.get("/api/summary/daily", params={"owner": "Bhavin"}).json()
    assert summary["due_reminders"] and all(r["owner"] == "Bhavin" for r in summary["due_reminders"])


def test_rerun_requires_llm_and_supersedes(client, monkeypatch):
    client.post("/api/capture/sample", params={"limit": 3})
    client.post("/api/capture/process")
    assert client.get("/api/capture/rerun").json()["rules_drafts"] == 3
    assert client.post("/api/capture/rerun").status_code == 409  # rules mode: refuse

    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    assert client.post("/api/capture/rerun", params={"limit": 2}).json()["requeued"] == 2
    status = client.get("/api/capture/rerun").json()
    assert status["rules_drafts"] == 1 and status["queued"] == 2
    assert len(client.get("/api/drafts", params={"status": "superseded"}).json()) == 2
