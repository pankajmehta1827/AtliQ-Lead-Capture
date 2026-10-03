"""LangChain chains (Groq) for classification, extraction and cross-sell suggestions."""
from __future__ import annotations

from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate

from ..catalogue import SOURCES, STAGES, catalogue_text
from ..config import get_settings
from .schemas import Classification, CrossSell, Extraction

CLASSIFY_SYSTEM = """You triage conversations for AtliQ Technologies, a software services company \
(custom software, data platforms, Power BI, AI solutions, staff augmentation).
AtliQ people use @{internal_domain} email addresses. Decide whether this item is sales-related.
An internal forward that reports on ONE specific client conversation counts as sales-related.
CRM context for this sender, if any: {crm_hint}"""

EXTRACT_SYSTEM = """You turn AtliQ sales conversations into CRM fields.
Rules:
- Only use facts stated in the conversation. If a value is not stated, return null. Never guess.
- Every non-null value MUST have an `evidence` quote copied verbatim from the conversation.
- The company and contact are the CLIENT side, never AtliQ (@{internal_domain}).
- service_interest must be one of: {services}
- source must be one of: {sources}
- stage must be one of: {stages}
- Today is {today}. The conversation is dated {item_date}. Resolve relative dates ("next Thursday",
  "Q4", "end of July", "check back in Q2 2026") to ISO dates; quarters resolve to the first day of the quarter.
- followups: include every commitment either side made, every revisit date, every request AtliQ has not
  answered yet and every deadline. Each must have a due date when one can be inferred.
- Masked values like [MASKED_CARD] must never be reproduced.

AtliQ service catalogue:
{catalogue}

Existing CRM record this conversation appears to belong to (may be empty):
{crm_context}"""

CROSSSELL_SYSTEM = """You suggest cross-sell / upsell ideas for ONE existing AtliQ client.
Use only this client's own history below and the AtliQ service catalogue. Do not mention other clients.
Only suggest an idea if the client expressed a need or pain; cite the exact quote. Return an empty list
if there is no evidence. Skip services the client already buys unless the need is clearly new.

AtliQ service catalogue:
{catalogue}

Client CRM history:
{history}"""


@lru_cache
def _model():
    from langchain_groq import ChatGroq

    s = get_settings()
    extra = {"reasoning_effort": "low"} if _is_gpt_oss() else {}
    return ChatGroq(
        model=s.groq_model,
        api_key=s.groq_api_key,
        temperature=s.llm_temperature,
        max_retries=2,
        timeout=90,
        **extra,
    )


def _is_gpt_oss() -> bool:
    return get_settings().groq_model.startswith("openai/gpt-oss")


def _structured(schema):
    # gpt-oss on Groq supports strict JSON-schema (constrained decoding): output always matches the schema.
    # Its tool calling is unreliable (skipped calls, schema mismatches), so we avoid it for these models.
    if _is_gpt_oss():
        return _model().with_structured_output(schema, method="json_schema", strict=True)
    return _model().with_structured_output(schema)


def classify_chain():
    prompt = ChatPromptTemplate.from_messages([("system", CLASSIFY_SYSTEM), ("human", "{conversation}")])
    return prompt | _structured(Classification)


def extract_chain():
    prompt = ChatPromptTemplate.from_messages([("system", EXTRACT_SYSTEM), ("human", "{conversation}")])
    return prompt | _structured(Extraction)


def crosssell_chain():
    prompt = ChatPromptTemplate.from_messages(
        [("system", CROSSSELL_SYSTEM), ("human", "Latest conversation:\n{conversation}")]
    )
    return prompt | _structured(CrossSell)


def prompt_constants() -> dict[str, str]:
    from ..catalogue import service_names

    return {
        "services": ", ".join(service_names()),
        "sources": ", ".join(SOURCES),
        "stages": ", ".join(STAGES),
        "catalogue": catalogue_text(),
        "internal_domain": get_settings().internal_domain,
    }
