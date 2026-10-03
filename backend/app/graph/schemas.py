"""Structured-output schemas the LLM must fill. Every value carries a verbatim evidence quote (FR-8).

Written to be compatible with Groq strict JSON-schema mode (constrained decoding): every property is
required (no defaults) and there are no numeric range keywords. "Not stated" is expressed as null."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["new_lead", "existing_deal", "existing_client", "not_sales"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Classification(_Strict):
    category: Category = Field(
        description=(
            "new_lead: a prospect/company AtliQ has not sold to before. existing_deal: an ongoing opportunity "
            "(proposal, negotiation, follow-up). existing_client: a company AtliQ already delivered work for, "
            "talking about support, renewal or new needs. not_sales: personal, recruiting, vendor/admin, "
            "newsletters, or internal discussion that covers many deals at once."
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
