"""Structured-output schemas the LLM must fill. Every value carries a verbatim evidence quote (FR-8)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["new_lead", "existing_deal", "existing_client", "not_sales"]


class Classification(BaseModel):
    category: Category = Field(
        description=(
            "new_lead: a prospect/company AtliQ has not sold to before. existing_deal: an ongoing opportunity "
            "(proposal, negotiation, follow-up). existing_client: a company AtliQ already delivered work for, "
            "talking about support, renewal or new needs. not_sales: personal, recruiting, vendor/admin, "
            "newsletters, or internal discussion that covers many deals at once."
        )
    )
    confidence: float = Field(ge=0, le=1, description="How sure you are, 0-1.")
    reason: str = Field(description="One short sentence explaining the category.")


class Field_(BaseModel):
    value: str | None = Field(default=None, description="The value, or null if not stated. Never guess.")
    evidence: str | None = Field(
        default=None, description="Exact quote (copied verbatim, max ~25 words) from the conversation supporting the value."
    )
    confidence: float = Field(default=0.0, ge=0, le=1)


class SummarySentence(BaseModel):
    text: str
    evidence: str = Field(description="Verbatim quote the sentence is based on.")


class FollowUp(BaseModel):
    reason: str = Field(description="What was committed or needs chasing, e.g. 'Client asked to revisit in Q2 2026'.")
    due_date: str | None = Field(description="ISO date YYYY-MM-DD when the follow-up is due. Resolve relative dates.")
    suggested_next_step: str
    owner_is_atliq: bool = Field(default=True, description="True if the action is on AtliQ's side.")
    evidence: str = Field(description="Verbatim quote showing the commitment or signal.")


class NewNeed(BaseModel):
    need: str
    evidence: str


class Extraction(BaseModel):
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
    summary: list[SummarySentence] = Field(description="3-5 plain sentences: what was discussed and agreed.")
    followups: list[FollowUp] = Field(default_factory=list, description="Commitments, revisit dates, unanswered requests.")
    new_needs: list[NewNeed] = Field(default_factory=list, description="Additional needs the client mentioned beyond the main topic.")


class CrossSellIdea(BaseModel):
    service: str = Field(description="AtliQ service from the catalogue.")
    rationale: str = Field(description="Why this client may need it, 1-2 sentences.")
    evidence: str = Field(description="Verbatim quote from THIS client's own conversation or CRM notes.")


class CrossSell(BaseModel):
    ideas: list[CrossSellIdea] = Field(default_factory=list)
