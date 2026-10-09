"""#1 multi-deal internal notes, #2 revisit dates, #4 email drafts, #5 ask your pipeline.

Rules-mode paths run as-is; AI paths use a stand-in model so the tests stay offline and deterministic."""
from pathlib import Path

import pytest

from app.graph import schemas as S

DATA = Path(__file__).resolve().parent.parent / "data"


class Fake:
    def __init__(self, out):
        self.out = out

    def invoke(self, _):
        return self.out


@pytest.fixture()
def ai_on(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    return monkeypatch


def _upload(client, rel, name):
    text = (DATA / rel).read_text(encoding="utf-8")
    r = client.post("/api/capture/upload", files={"files": (name, text.encode(), "text/markdown")})
    assert r.status_code == 200, r.text
    client.post("/api/capture/process", params={"limit": 10})


# ---------------------------------------------------------------- #1

def test_internal_pipeline_review_becomes_one_update_per_deal(client):
    _upload(client, "meeting_notes/2026-07-02_internal_pipeline_review.md", "meeting_notes_pipeline_review.md")
    drafts = [d for d in client.get("/api/drafts", params={"status": "pending"}).json()
              if "pipeline_review" in (d["source"]["external_ref"] or "")]
    codes = {d["deal_lead_code"] for d in drafts}
    assert {"L-1029", "L-1026"} <= codes  # NovaPharma and Sunrise Foods
    assert all(d["kind"] == "update" and d["summary"].startswith("From internal note") for d in drafts)
    assert all(d["source"]["category"] == "internal_multi_deal" for d in drafts)
    assert len(codes) == len(drafts)  # never two drafts for the same deal


def test_multi_deal_ai_path_drops_ungrounded_and_matches_by_company(client, ai_on):
    from app.graph import llm

    ai_on.setattr(llm, "classify_chain", lambda: Fake(S.Classification(category="internal_multi_deal", confidence=0.9, reason="review")))
    ai_on.setattr(llm, "multi_chain", lambda: Fake(S.MultiDeal(deals=[
        S.DealMention(company="NovaPharma", lead_code=None, update="Security questionnaire deadline is real.",
                      next_step="Assign an owner for the security questionnaire", next_step_date="2026-07-24",
                      owner=None, evidence="NovaPharma security questionnaire deadline is real"),
        S.DealMention(company="Sunrise Foods", lead_code=None, update="Wants a v2.", next_step=None,
                      next_step_date=None, owner="Dhaval", evidence="this sentence is not in the note"),
    ])))
    _upload(client, "meeting_notes/2026-07-02_internal_pipeline_review.md", "meeting_notes_review_ai.md")
    drafts = [d for d in client.get("/api/drafts").json() if "review_ai" in (d["source"]["external_ref"] or "")]
    assert [d["deal_lead_code"] for d in drafts] == ["L-1029"]  # Sunrise dropped: its quote isn't in the note
    assert drafts[0]["followups"][0]["due_date"] == "2026-07-24"


# ---------------------------------------------------------------- #2

def test_quantia_revisit_becomes_revisit_reminder(client):
    _upload(client, "emails/2025-09-30_quantia_lost_deal.md", "quantia.md")
    d = next(d for d in client.get("/api/drafts").json() if (d["source"]["external_ref"] or "").endswith("quantia.md"))
    rev = [f for f in d["followups"] if f.get("kind") == "revisit"]
    assert rev and rev[0]["due_date"] == "2026-04-01"
    client.post(f"/api/drafts/{d['id']}/confirm", json={})
    rems = client.get("/api/reminders", params={"status": "open"}).json()
    assert any(r["kind"] == "revisit" and r["lead_code"] == "L-1035" and r["due_date"] == "2026-04-01" for r in rems)


def test_healthfirst_board_date_detected(client):
    _upload(client, "emails/2026-04-20_healthfirst_board_update.md", "healthfirst.md")
    d = next(d for d in client.get("/api/drafts").json() if (d["source"]["external_ref"] or "").endswith("healthfirst.md"))
    assert any(f["due_date"] == "2026-07-14" for f in d["followups"])


# ---------------------------------------------------------------- #4

def test_email_draft_rules_mode(client):
    client.post("/api/reminders/scan")
    finedge = next(d for d in client.get("/api/deals").json() if d["lead_code"] == "L-1023")
    r = client.post(f"/api/deals/{finedge['id']}/email-draft", json={})
    assert r.status_code == 200
    e = r.json()
    assert e["mode"] == "rules" and e["to_email"] == "suresh.menon@finedge.com" and "Suresh" in e["body"]
    assert any(a["action"] == "email_drafted" for a in client.get("/api/audit").json())


def test_email_draft_ai_flags_unverified_facts(client, ai_on):
    from app.graph import llm

    ai_on.setattr(llm, "email_chain", lambda: Fake(S.EmailDraft(
        subject="FinEdge: commercial discussion", body="Hi Suresh, ...", facts=[
            S.Fact(fact="Proposal is in Proposal Sent", evidence="status Proposal Sent"),
            S.Fact(fact="A 20% discount was offered", evidence="we offered a 20% discount"),
        ])))
    finedge = next(d for d in client.get("/api/deals").json() if d["lead_code"] == "L-1023")
    e = client.post(f"/api/deals/{finedge['id']}/email-draft", json={"instructions": "shorter"}).json()
    assert e["mode"] == "llm" and e["unverified"] == 1
    assert [f["grounded"] for f in e["facts"]] == [True, False]


# ---------------------------------------------------------------- #5

def test_ask_rules_mode_focuses_named_deal(client):
    r = client.post("/api/ask", json={"question": "What's happening with FinEdge?"}).json()
    assert r["mode"] == "rules" and [d["lead_code"] for d in r["deals"]] == ["L-1023"]


def test_ask_ai_path_links_deals_and_checks_quotes(client, ai_on):
    from app.graph import llm

    ai_on.setattr(llm, "ask_chain", lambda: Fake(S.PipelineAnswer(
        answer="FinEdge (L-1023) is waiting on a commercial call.", deals=["L-1023", "L-9999"],
        citations=[S.Citation(lead_code="L-1023", quote="L-1023 | FinEdge Bank"),
                   S.Citation(lead_code=None, quote="made-up quote")])))
    r = client.post("/api/ask", json={"question": "Why is FinEdge stuck?",
                                      "history": [{"role": "user", "content": "hi"}]}).json()
    assert [d["lead_code"] for d in r["deals"]] == ["L-1023"]  # unknown ids are dropped
    assert [c["grounded"] for c in r["citations"]] == [True, False]
