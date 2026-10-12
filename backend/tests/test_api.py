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


def test_review_queue_newest_first(client):
    """A lead change just captured from an email or meeting note goes to the top of the queue."""
    client.post("/api/capture/sample")
    client.post("/api/capture/process", params={"limit": 50})
    r = client.post("/api/capture", json={
        "channel": "email",
        "text": "Hi Jay, we would like a data platform for our 12 stores. Budget 40k. Can we talk on 22 Jul?",
        "contact_name": "Ravi Shah", "contact_email": "ravi@kitebrook.in", "subject": "KiteBrook data platform",
    })
    assert r.status_code == 200
    client.post("/api/capture/process")
    drafts = client.get("/api/drafts").json()
    assert drafts[0]["source"]["subject"] == "KiteBrook data platform"
    stamps = [d["created_at"] for d in drafts]
    assert stamps == sorted(stamps, reverse=True)


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


def test_crm_list_create_export_import_and_ai_sync(client):
    leads = client.get("/api/crm/leads").json()
    assert len(leads) == 40 and all(l["origin"] == "crm_export" for l in leads)
    assert {"Won", "Lost"} & {l["status"] for l in leads}  # closed deals are in the CRM too

    # manual add, duplicate guard
    dup = client.post("/api/crm/leads", json={"company": "GreenGrid Solar", "contact_email": "aditya@greengrid.in"})
    assert dup.status_code == 409
    new = client.post("/api/crm/leads", json={"company": "Orbit Mills", "contact_email": "ops@orbitmills.in",
                                               "status": "New", "est_value_usd": 12000})
    assert new.status_code == 200 and new.json()["lead_code"] == "L-1041"
    assert next(l for l in client.get("/api/crm/leads").json() if l["lead_code"] == "L-1041")["origin"] == "manual"

    # CSV export round-trips through import (no changes)
    csv_text = client.get("/api/crm/export").text
    assert csv_text.startswith("lead_id,company,contact_name")
    r = client.post("/api/crm/import", files={"file": ("crm.csv", csv_text.encode(), "text/csv")})
    assert r.json()["created"] == 0 and r.json()["updated"] == 0

    # Excel import: update one existing lead, add one new
    import io
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["lead_id", "company", "status", "next_followup_date"])
    ws.append(["L-1023", "FinEdge Bank", "Proposal Sent", "2026-07-15"])
    ws.append([None, "Brightwave Labs", "New", None])
    buf = io.BytesIO(); wb.save(buf)
    r = client.post("/api/crm/import", files={"file": ("crm.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.json()["created"] == 1 and r.json()["updated"] == 1
    finedge = next(l for l in client.get("/api/crm/leads").json() if l["lead_code"] == "L-1023")
    assert finedge["next_followup_date"] == "2026-07-15"
    assert client.get("/api/crm/export", params={"format": "xlsx"}).content[:2] == b"PK"

    # AI Lead app -> CRM: a confirmed draft shows up as an AI write
    client.post("/api/capture/sample", params={"limit": 34})
    client.post("/api/capture/process", params={"limit": 50})
    pixel = next(d for d in client.get("/api/drafts").json() if "pixelworks" in d["source"]["external_ref"])
    client.post(f"/api/drafts/{pixel['id']}/confirm", json={"edits": {"company": "PixelWorks Agency", "next_step": "Reply"}})
    sync = client.get("/api/crm/sync").json()
    assert sync["ai_created"] == 1 and sync["recent"][0]["company"] == "PixelWorks Agency"
    px = next(l for l in client.get("/api/crm/leads").json() if l["company"] == "PixelWorks Agency")
    assert px["origin"] == "ai_capture"


def test_reminder_deadline_reflects_how_late_the_deal_is(client):
    client.post("/api/reminders/scan")
    rems = client.get("/api/reminders", params={"owner": "Bhavin"}).json()
    finedge = next(r for r in rems if r["lead_code"] == "L-1023" and r["kind"] == "proposal_unanswered")
    # last contact 2026-03-30 + 7 days, not the scan date
    assert finedge["due_date"] == "2026-07-10" and finedge["deadline"] == "2026-04-06"


def test_remove_conversation_reverts_crm(client):
    """Removing a captured conversation deletes its drafts and reminders and undoes the CRM changes it confirmed."""
    deals = client.get("/api/deals").json()
    deals = deals if isinstance(deals, list) else deals["deals"]
    vertex = next(d for d in deals if d["lead_code"] == "L-1037")
    before = client.get(f"/api/deals/{vertex['id']}").json()
    before_deal = before["deal"]

    r = client.post("/api/capture", json={
        "channel": "email", "subject": "Site progress app timing",
        "text": "From: P. Naidu <naidu@vertexcon.in>\nDate: 2026-07-06\n\nJay, the board approved budget for Q4. "
                "Please check back with me in early October.",
    })
    item_id = r.json()["item"]["id"]
    client.post("/api/capture/process")
    draft = next(d for d in client.get("/api/drafts").json() if d["source"]["id"] == item_id)
    client.post(f"/api/drafts/{draft['id']}/confirm", json={
        "target_deal_id": vertex["id"], "edits": {"next_step": "Restart the site progress app",
                                                  "next_step_date": "2026-10-01"}})
    changed = client.get(f"/api/deals/{vertex['id']}").json()["deal"]
    assert changed["next_step"] == "Restart the site progress app"

    out = client.post("/api/admin/conversations/remove", json={"ids": [item_id]}).json()
    assert out["removed"][0]["id"] == item_id and "L-1037" in out["deals_reverted"]
    after = client.get(f"/api/deals/{vertex['id']}").json()
    for k in ("next_step", "next_followup_date", "last_contact_date", "notes", "status", "owner", "contact_email"):
        assert after["deal"].get(k) == before_deal.get(k), k
    assert len(after["activities"]) == len(before["activities"])
    # reminders that came from this conversation are gone (the scanner's own health reminders may remain)
    assert not [r for r in after["reminders"] if r["source"] and r["source"]["id"] == item_id]
    assert not [d for d in client.get("/api/drafts", params={"status": "confirmed"}).json()
                if d["source"] and d["source"]["id"] == item_id]
    assert all(i["id"] != item_id for i in client.get("/api/capture/items").json()["items"])
    # the same text can now be captured again as a new conversation
    again = client.post("/api/capture", json={"channel": "email", "subject": "Site progress app timing",
                                              "text": "From: P. Naidu <naidu@vertexcon.in>\nDate: 2026-07-06\n\nJay, "
                                                      "the board approved budget for Q4. Please check back with me "
                                                      "in early October."}).json()
    assert again["created"] is True
