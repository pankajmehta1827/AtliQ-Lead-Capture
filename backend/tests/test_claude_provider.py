"""LLM_PROVIDER=anthropic: captured conversations go to Claude; email drafts and Ask AI stay on Groq."""
from types import SimpleNamespace

import pytest

from app.graph import schemas as S


class FakeMessages:
    def __init__(self, out, stop_reason="end_turn"):
        self.out, self.stop_reason, self.calls = out, stop_reason, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.out)


@pytest.fixture()
def claude(monkeypatch):
    from app.config import get_settings
    from app.graph import llm

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    monkeypatch.setattr(s, "anthropic_api_key", "test-claude-key")
    monkeypatch.setattr(s, "groq_api_key", "test-groq-key")

    def use(out, stop_reason="end_turn"):
        fake = SimpleNamespace(messages=FakeMessages(out, stop_reason))
        monkeypatch.setattr(llm, "_claude", lambda: fake)
        return fake.messages

    return use


def test_capture_chains_call_claude_with_schema_and_effort(claude):
    from app.graph import llm

    out = S.Classification(category="new_lead", confidence=0.9, reason="inbound enquiry")
    calls = claude(out)
    result = llm.classify_chain().invoke({
        "conversation": "Hello, we need a dashboard.", "internal_domain": "atliq.com",
        "crm_hint": "none", "mentioned": "none",
    })
    assert result == out
    call = calls.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_format"] is S.Classification
    assert call["output_config"] == {"effort": "low"}
    assert "temperature" not in call  # current Claude models reject non-default sampling
    assert "AtliQ" in call["system"] and call["messages"] == [{"role": "user", "content": "Hello, we need a dashboard."}]


def test_email_drafts_and_ask_stay_on_groq(claude):
    from app.graph import llm

    calls = claude(None)
    for chain in (llm.email_chain(), llm.ask_chain()):
        assert type(chain).__name__ == "RunnableSequence"  # prompt | Groq structured model
    assert calls.calls == []


def test_refusal_is_raised_not_parsed(claude):
    from app.graph import llm

    claude(None, stop_reason="refusal")
    with pytest.raises(llm.ClaudeRefusal):
        llm.dates_chain().invoke({"conversation": "x", "today": "2026-07-10", "item_date": "2026-07-10"})


def test_capture_switch_needs_the_claude_key(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    monkeypatch.setattr(s, "anthropic_api_key", None)
    monkeypatch.setattr(s, "groq_api_key", "test-groq-key")
    assert not s.capture_llm_enabled  # falls back to rules mode for capture
    assert s.llm_enabled  # Groq features unaffected
    monkeypatch.setattr(s, "llm_provider", "groq")
    assert s.capture_llm_enabled


def test_claude_rate_limit_uses_retry_after_header():
    from app.services.capture import _retry_after_header

    exc = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "120"}))
    assert _retry_after_header(exc) == 121
    assert _retry_after_header(Exception("no response")) is None


def test_email_provider_anthropic_sends_drafts_to_claude_but_ask_stays_on_groq(claude, monkeypatch):
    from app.config import get_settings
    from app.graph import llm

    monkeypatch.setattr(get_settings(), "email_provider", "anthropic")
    draft = S.EmailDraft(subject="Following up", body="Hi Priya, ...", facts=[])
    calls = claude(draft)
    out = llm.email_chain().invoke({"sender": "Dhaval", "recipient": "Priya", "instructions": "none",
                                    "context": "Deal L-1001 Acme Retail Group"})
    assert out == draft
    assert calls.calls[0]["model"] == "claude-haiku-5-5" and calls.calls[0]["output_format"] is S.EmailDraft
    assert type(llm.ask_chain()).__name__ == "RunnableSequence"  # Ask AI: Groq
    assert get_settings().email_llm_enabled
