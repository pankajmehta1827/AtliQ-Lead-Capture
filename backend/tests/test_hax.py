"""HAX guideline features: Confirm preview (G16) and feedback on AI output (G15)."""


def _drafts(client):
    client.post("/api/capture/sample", params={"limit": 40})
    for _ in range(5):
        client.post("/api/capture/process", params={"limit": 50})
    return client.get("/api/drafts").json()


def test_preview_shows_changes_and_saves_nothing(client):
    drafts = _drafts(client)
    audit_before = len(client.get("/api/audit").json())

    # new lead: lists the fields it will set, with the next lead code
    pixel = next(d for d in drafts if "pixelworks" in d["source"]["external_ref"])
    body = {"edits": {"company": "PixelWorks Agency", "next_step": "Reply to Tara", "next_step_date": "2026-07-12"}}
    p = client.post(f"/api/drafts/{pixel['id']}/preview", json=body)
    assert p.status_code == 200, p.text
    p = p.json()
    assert p["action"] == "create" and p["lead_code"] == "L-1041"
    fields = {c["field"]: c for c in p["changes"]}
    assert fields["company"]["to"] == "PixelWorks Agency" and fields["next_step"]["to"] == "Reply to Tara"
    assert any(r["due_date"] == "2026-07-12" for r in p["reminders"])

    # update: before -> after per field
    finedge = next(d for d in drafts if d["source"]["external_ref"].endswith("finedge_compliance_docs.md"))
    u = client.post(f"/api/drafts/{finedge['id']}/preview", json={"edits": {"next_step": "Send the SOC 2 pack"}}).json()
    assert u["action"] == "update" and u["lead_code"] == "L-1023"
    assert any(c["field"] == "next_step" and c["to"] == "Send the SOC 2 pack" for c in u["changes"])

    # nothing was written: no new deal, drafts still pending, deal unchanged, nothing logged
    assert len(client.get("/api/deals", params={"open_only": False}).json()) == 40
    assert client.get(f"/api/drafts/{pixel['id']}").json()["status"] == "pending"
    deal = next(d for d in client.get("/api/deals").json() if d["lead_code"] == "L-1023")
    assert deal["next_step"] != "Send the SOC 2 pack"
    assert len(client.get("/api/audit").json()) == audit_before

    # and the real confirm still works afterwards
    assert client.post(f"/api/drafts/{pixel['id']}/confirm", json=body).status_code == 200


def test_feedback_is_logged(client):
    r = client.post("/api/feedback", json={"feature": "email_draft", "rating": "down", "deal_id": 1,
                                          "comment": "Too formal"})
    assert r.status_code == 200
    entry = next(a for a in client.get("/api/audit").json() if a["action"] == "ai_feedback")
    assert entry["outcome"] == "down" and entry["details"]["comment"] == "Too formal"
    assert client.post("/api/feedback", json={"feature": "x", "rating": "up"}).status_code == 422
