from datetime import date
from pathlib import Path

from app.graph.grounding import evidence_in_source, ground_extraction
from app.masking import mask_sensitive
from app.matching import company_similarity, normalize_company
from app.parsing import parse_markdown_item

DATA = Path(__file__).resolve().parent.parent / "data"


def test_parse_email_thread_strips_editorial_notes():
    text = (DATA / "emails" / "2026-03-26_finedge_compliance_docs.md").read_text(encoding="utf-8")
    item = parse_markdown_item(text, "emails/x.md")
    assert item["channel"] == "email"
    assert item["sender_email"] == "suresh.menon@finedge.com"
    assert item["last_sender_email"] == "suresh.menon@finedge.com"
    assert item["occurred_at"] == date(2026, 6, 19)
    assert "No confirmation sent" not in item["body"]  # ground-truth note removed
    emails = {p["email"] for p in item["participants"]}
    assert {"suresh.menon@finedge.com", "bhavin@atliq.com"} <= emails


def test_parse_meeting_notes():
    text = (DATA / "meeting_notes" / "2026-07-09_greengrid_discovery.md").read_text(encoding="utf-8")
    item = parse_markdown_item(text, "meeting_notes/x.md", "meeting")
    assert item["channel"] == "meeting"
    assert item["occurred_at"] == date(2026, 7, 9)
    assert any(p["name"] == "Jay" for p in item["participants"])


def test_masking():
    masked, counts = mask_sensitive(
        "Card 4111 1111 1111 1111, password: hunter2, account no 123456789012, IFSC HDFC0001234, key sk-abcdefghijklmnop1234"
    )
    for secret in ("4111", "hunter2", "123456789012", "HDFC0001234", "abcdefghijklmnop"):
        assert secret not in masked
    assert counts["CARD"] == 1
    # ordinary business numbers survive
    assert mask_sensitive("Budget ~35k, call on 2026-07-09 at 10:30")[0] == "Budget ~35k, call on 2026-07-09 at 10:30"


def test_company_matching():
    assert normalize_company("Acme Retail Group") == "acme retail"
    assert company_similarity("Meridian Healthcare", "Meridian Health LLC") >= 0.85
    assert company_similarity("GreenGrid Solar", "Greengrid solar") == 1.0
    assert company_similarity("NovaPharma", "Northwind Logistics") < 0.6


def test_grounding_drops_invented_values():
    src = "Aditya indicated 20-25k comfortable for phase 1. Proposal by 17 Jul."
    ex = {
        "budget": {"value": "20-25k", "evidence": "20-25k comfortable for phase 1", "confidence": 0.9},
        "timeline": {"value": "December", "evidence": "go live in December", "confidence": 0.9},
        "summary": [{"text": "x", "evidence": "Proposal by 17 Jul"}, {"text": "y", "evidence": "invented"}],
        "followups": [], "new_needs": [],
    }
    out, dropped = ground_extraction(ex, src)
    assert out["budget"]["value"] == "20-25k"
    assert out["timeline"]["value"] is None and dropped == ["timeline"]
    assert len(out["summary"]) == 1
    assert evidence_in_source("proposal  by 17 jul", src)


def test_grounding_ignores_values_quoted_from_crm_context():
    src = "Neha: we need the vendor portal live by October."
    crm = "L-1004 | GlobalMart | status Proposal Sent"
    ex = {
        "stage": {"value": "Proposal Sent", "evidence": "status Proposal Sent", "confidence": 0.9},
        "timeline": {"value": "October", "evidence": "live by October", "confidence": 0.9},
        "summary": [], "followups": [], "new_needs": [],
    }
    out, dropped = ground_extraction(ex, src, crm)
    assert out["stage"]["value"] is None and dropped == []  # repeats CRM: not new, not an error
    assert out["timeline"]["value"] == "October"


def test_friendly_error_hides_provider_details():
    from app.serializers import friendly_error

    raw = "RateLimitError: Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x`"
    msg = friendly_error(raw)
    assert "gpt" not in msg and "org_" not in msg and "limit" in msg
    assert friendly_error(None) is None
