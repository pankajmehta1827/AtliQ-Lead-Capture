"""Structured-output schemas the LLM must fill. Every value carries a verbatim evidence quote (FR-8).

Written to be compatible with Groq strict JSON-schema mode (constrained decoding): every property is
required (no defaults) and there are no numeric range keywords. "Not stated" is expressed as null."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["new_lead", "existing_deal", "existing_client", "internal_multi_deal", "not_sales"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Classification(_Strict):
    category: Category = Field(
        description=(
            "new_lead: a prospect/company AtliQ has not sold to before. existing_deal: an ongoing opportunity "
            "(proposal, negotiation, follow-up). existing_client: a company AtliQ already delivered work for, "
            "talking about support, renewal or new needs. internal_multi_deal: an internal AtliQ meeting note "
            "or email that discusses several specific client deals (e.g. a pipeline review). not_sales: "
            "personal, recruiting, vendor/admin, newsletters, or internal talk that names no specific client deal."
        )
    )
    confidence: float = Field(description="How sure you are, between 0 and 1.")
    reason: str = Field(description="One short sentence explaining the category.")


class Field_(_Strict):
    value: str | None = Field(description="The value, or null if not stated. Never guess.")
    evidence: str | None = Field(
        description="Exact quote (copied verbatim, max ~25 words) from the conversation supporting the value; null if value is null."
    )
    confidence: float = Field(description="Between 0 and 1; 0 if value is null.")


class SummarySentence(_Strict):
    text: str
    evidence: str = Field(description="Verbatim quote the sentence is based on.")


class FollowUp(_Strict):
    reason: str = Field(description="What was committed or needs chasing, e.g. 'Client asked to revisit in Q2 2026'.")
    due_date: str | None = Field(description="ISO date YYYY-MM-DD when the follow-up is due. Resolve relative dates.")
    suggested_next_step: str
    owner_is_atliq: bool = Field(description="True if the action is on AtliQ's side.")
    evidence: str = Field(description="Verbatim quote showing the commitment or signal.")


class NewNeed(_Strict):
    need: str
    evidence: str


class Extraction(_Strict):
    company: Field_ = Field(description="Client / prospect company name (not AtliQ).")
    contact_name: Field_ = Field(description="Main client-side contact person.")
    contact_email: Field_ = Field(description="Client contact's email address.")
    source: Field_ = Field(description="How the lead reached AtliQ: Referral, LinkedIn, Conference, Website, Cold Outreach, Existing Client or Partner.")
    service_interest: Field_ = Field(description="Closest AtliQ service line from the catalogue.")
    requirement: Field_ = Field(description="What the client needs, in one plain sentence.")
    budget: Field_ = Field(description="Budget or deal value if stated, e.g. '20-25k USD'.")
    timeline: Field_ = Field(description="Client deadline / timing driver if stated.")
    stage: Field_ = Field(description="Deal stage: New, Contacted, Proposal Sent, Won or Lost.")
    next_step: Field_ = Field(description="The agreed or obviously required next action for AtliQ.")
    next_step_date: Field_ = Field(description="ISO date YYYY-MM-DD for the next step, if one is stated or implied.")
    summary: list[SummarySentence] | None = Field(description="3-5 plain sentences: what was discussed and agreed.")
    followups: list[FollowUp] | None = Field(description="Commitments, revisit dates, unanswered requests. Empty list if none.")
    new_needs: list[NewNeed] | None = Field(description="Additional needs the client mentioned beyond the main topic. Empty list if none.")


class CrossSellIdea(_Strict):
    service: str = Field(description="AtliQ service from the catalogue.")
    rationale: str = Field(description="Why this client may need it, 1-2 sentences.")
    evidence: str = Field(description="Verbatim quote from THIS client's own conversation or CRM notes.")


class CrossSell(_Strict):
    ideas: list[CrossSellIdea] | None = Field(description="Empty list if there is no evidence of a need.")


# ---------------------------------------------------------------- revisit / date signals (#2)

class DateSignal(_Strict):
    phrase: str = Field(description="The time expression exactly as written, e.g. 'likely Q2 2026', 'now scheduled for 14 July'.")
    resolved_date: str | None = Field(description="ISO date YYYY-MM-DD it refers to; quarters = first day of the quarter; null if it cannot be resolved.")
    kind: Literal["revisit", "deadline", "meeting", "decision", "other"] = Field(
        description="revisit: client asked to reconnect later / deal paused until then. deadline: something is due. "
        "meeting: a call or meeting is planned. decision: a client decision or approval is expected. other: anything else."
    )
    what: str = Field(description="What should happen on that date, phrased as an action for AtliQ, e.g. 'Check back with James after the acquisition closes'.")
    evidence: str = Field(description="Verbatim quote containing the time expression. Max 25 words; never include double-quote characters.")


class DateSignals(_Strict):
    signals: list[DateSignal] | None = Field(description="Every FUTURE-looking time reference relevant to the deal. Empty list if none.")


# ---------------------------------------------------------------- internal notes covering several deals (#1)

class DealMention(_Strict):
    company: str = Field(description="Client company the point is about, as written.")
    lead_code: str | None = Field(description="CRM id like L-1023 if the note cites one, else null.")
    update: str = Field(description="One sentence: what the note says about this deal (status, blocker, decision).")
    next_step: str | None = Field(description="The action AtliQ should take for this deal, if stated or clearly implied.")
    next_step_date: str | None = Field(description="ISO date for that action or deadline, if stated or inferable.")
    owner: str | None = Field(description="AtliQ person who owns or took the action, if named.")
    evidence: str = Field(description="Verbatim quote from the note about this deal. Max 25 words; never include double-quote characters.")


class MultiDeal(_Strict):
    deals: list[DealMention] | None = Field(description="One entry per client deal discussed. Empty list if none.")


# ---------------------------------------------------------------- follow-up email draft (#4)

class Fact(_Strict):
    fact: str = Field(description="A fact the email relies on.")
    evidence: str = Field(description="Verbatim quote from the CONTEXT supporting it. Max 25 words; never include double-quote characters.")


class EmailDraft(_Strict):
    subject: str
    body: str = Field(description="Plain-text email body, greeting to sign-off. No placeholders except [your availability].")
    facts: list[Fact] | None = Field(description="Every client-specific fact used in the email, each with a quote from the context.")


# ---------------------------------------------------------------- ask your pipeline (#5)

class Citation(_Strict):
    lead_code: str | None = Field(description="CRM id the quote belongs to, if any.")
    quote: str = Field(description="Verbatim quote from the CONTEXT that supports the answer. Max 25 words; never include double-quote characters.")


class PipelineAnswer(_Strict):
    answer: str = Field(description="Direct answer in plain language. Short paragraphs or '- ' bullet lines. Say plainly if the context does not contain the answer.")
    deals: list[str] | None = Field(description="CRM ids (L-xxxx) the answer is about.")
    citations: list[Citation] | None = Field(description="Quotes from the context that support the answer.")
