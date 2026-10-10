"""LangChain chains. Capture pipeline: Groq, or Claude with LLM_PROVIDER=anthropic. Email drafts: Groq, or Claude
with EMAIL_PROVIDER=anthropic. Ask AI: always Groq."""
from __future__ import annotations

from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate

from ..catalogue import SOURCES, STAGES, catalogue_text
from ..config import get_settings
from .schemas import Classification, CrossSell, DateSignals, EmailDraft, Extraction, MultiDeal, PipelineAnswer

CLASSIFY_SYSTEM = """You triage conversations for AtliQ Technologies, a software services company \
(custom software, data platforms, Power BI, AI solutions, staff augmentation).
AtliQ people use @{internal_domain} email addresses. Decide whether this item is sales-related.
An internal forward that reports on ONE specific client conversation counts as sales-related.
An internal note or meeting that discusses SEVERAL client deals (e.g. a pipeline review) is internal_multi_deal.
CRM context for this sender, if any: {crm_hint}
CRM deals named in the text: {mentioned}"""

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

Existing CRM record this conversation appears to belong to (may be empty). It is background only:
never quote it as evidence, and only return a field if THIS conversation states or changes it.
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
def _model(temperature: float | None = None):
    from langchain_groq import ChatGroq

    s = get_settings()
    extra = {"reasoning_effort": "low"} if _is_gpt_oss() else {}
    return ChatGroq(
        model=s.groq_model,
        api_key=s.groq_api_key,
        temperature=s.llm_temperature if temperature is None else temperature,
        max_retries=2,
        timeout=90,
        **extra,
    )


def _is_gpt_oss() -> bool:
    return get_settings().groq_model.startswith("openai/gpt-oss")


def _bind(model, schema):
    # gpt-oss on Groq supports strict JSON-schema (constrained decoding): output always matches the schema.
    # Its tool calling is unreliable (skipped calls, schema mismatches), so we avoid it for these models.
    if _is_gpt_oss():
        return model.with_structured_output(schema, method="json_schema", strict=True)
    return model.with_structured_output(schema)


def _structured(schema):
    # Groq occasionally rejects a generation whose JSON is malformed (400 json_validate_failed, e.g. a quote
    # with stray escaped double quotes). Retrying at the same temperature reproduces it, so the single retry
    # runs slightly warmer. Only 400s are retried: rate limits must reach the worker's back-off unchanged.
    from groq import BadRequestError

    primary = _bind(_model(), schema)
    return primary.with_fallbacks([_bind(_model(0.4), schema)], exceptions_to_handle=(BadRequestError,))


DATES_SYSTEM = """You find time references in an AtliQ sales conversation that should trigger a follow-up.
Today is {today}. The conversation is dated {item_date}.
List every FUTURE-looking time reference: revisit dates ("check back around Q2", "after the acquisition closes,
likely Q2 2026"), deferrals ("decision deferred to the 14 July board"), deadlines ("SOW by 15 July", "questionnaire
due 24 July"), planned meetings and expected decisions. Ignore dates that are only history.
Resolve each to an ISO date relative to the conversation date: quarters -> first day of the quarter, "end of July"
-> last day of July, weekdays -> the next such day after the conversation date. Use null if it cannot be resolved.
Copy the evidence verbatim. Never invent a date that is not in the text."""

MULTI_SYSTEM = """You read an INTERNAL AtliQ note or meeting that discusses several client deals.
For each client deal discussed, return one entry: the company, its CRM id if cited (e.g. L-1023), a one-sentence
update, the next step for AtliQ and its date if stated or clearly implied, the AtliQ owner if named, and a
verbatim quote. Today is {today}; the note is dated {item_date}; resolve relative dates to ISO dates.
Skip AtliQ itself and general process remarks that are not about a specific client.
Known CRM deals (use these ids when the company matches): {deals}"""

EMAIL_SYSTEM = """You draft a short follow-up email for an AtliQ seller to send to a client. The seller will review,
edit and send it themselves; you never send anything.
Rules:
- Write as {sender} from AtliQ to {recipient}. Warm, specific, professional, under 150 words, no buzzwords.
- Use ONLY facts from the CONTEXT below. Do not invent prices, dates, deliverables, names or promises.
- Address the most important open point first (reason for the follow-up), then propose one clear next step.
- Use the most recent conversation as the truth; CRM notes may be stale. Today is in the CONTEXT: never propose
  a date that is already past, and acknowledge a delay on AtliQ's side briefly if the client has been waiting.
- If a time slot is needed write [your availability] rather than inventing one.
- List every client-specific fact you used in `facts`, each with a verbatim quote from the CONTEXT.
- Never include masked values like [MASKED_CARD].
Extra instructions from the seller (may be empty): {instructions}

CONTEXT
{context}"""

ASK_SYSTEM = """You are AtliQ's pipeline assistant. Answer the seller's question using ONLY the CONTEXT: a snapshot
of every CRM deal, plus details and recent conversations for the deals the question is about.
Today is {today}. Be direct and specific: name deals with their CRM id, amounts, owners, dates and blockers.
Information changes over time: CRM notes and statuses are often stale. When a dated conversation is newer than
the CRM record, trust the conversation, and point out that the CRM is out of date. Dates already in the past
relative to today are missed, not upcoming.
If the context does not contain the answer, say so plainly; never guess. Cite the quotes you relied on.
You give information only: you never contact clients or change the CRM.

CONTEXT
{context}"""


@lru_cache
def _claude():
    import anthropic

    s = get_settings()
    # explicit base_url: never inherit an ANTHROPIC_BASE_URL meant for another tool on the same machine
    return anthropic.Anthropic(api_key=s.anthropic_api_key, base_url="https://api.anthropic.com", max_retries=2, timeout=120)


class ClaudeRefusal(RuntimeError):
    pass


def _claude_structured(prompt: ChatPromptTemplate, schema, model: str, effort: str):
    """Same contract as `prompt | _structured(schema)`: invoke(dict) -> a validated `schema` instance.

    Uses the Messages API structured outputs (`messages.parse` + `output_format`), so the reply always matches the
    schema. No temperature: current Claude models reject non-default sampling values."""
    from langchain_core.runnables import RunnableLambda

    def call(inputs: dict):
        msgs = prompt.format_messages(**inputs)
        system = "\n\n".join(str(m.content) for m in msgs if m.type == "system")
        turns = [{"role": "assistant" if m.type == "ai" else "user", "content": str(m.content)}
                 for m in msgs if m.type != "system"]
        response = _claude().messages.parse(
            model=model,
            max_tokens=16000,
            system=system,
            messages=turns,
            output_format=schema,
            output_config={"effort": effort},
        )
        if response.stop_reason == "refusal":
            raise ClaudeRefusal("Claude declined to process this conversation")
        if response.parsed_output is None:
            raise ValueError(f"Claude returned no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output

    return RunnableLambda(call)


def _capture_chain(system: str, human: str, schema):
    """Chains that read captured conversations: Claude when LLM_PROVIDER=anthropic, else Groq."""
    s = get_settings()
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    if s.capture_provider == "anthropic":
        return _claude_structured(prompt, schema, s.capture_claude_model, s.capture_claude_effort)
    return prompt | _structured(schema)


def dates_chain():
    return _capture_chain(DATES_SYSTEM, "{conversation}", DateSignals)


def multi_chain():
    return _capture_chain(MULTI_SYSTEM, "{conversation}", MultiDeal)


def email_chain():
    """Follow-up email drafts: Claude when EMAIL_PROVIDER=anthropic, else Groq."""
    s = get_settings()
    prompt = ChatPromptTemplate.from_messages([("system", EMAIL_SYSTEM), ("human", "Write the follow-up email.")])
    if s.email_provider_name == "anthropic":
        return _claude_structured(prompt, EmailDraft, s.email_claude_model, s.email_claude_effort)
    return prompt | _structured(EmailDraft)


def ask_chain():
    prompt = ChatPromptTemplate.from_messages(
        [("system", ASK_SYSTEM), ("placeholder", "{history}"), ("human", "{question}")]
    )
    return prompt | _structured(PipelineAnswer)


def classify_chain():
    return _capture_chain(CLASSIFY_SYSTEM, "{conversation}", Classification)


def extract_chain():
    return _capture_chain(EXTRACT_SYSTEM, "{conversation}", Extraction)


def crosssell_chain():
    return _capture_chain(CROSSSELL_SYSTEM, "Latest conversation:\n{conversation}", CrossSell)


def prompt_constants() -> dict[str, str]:
    from ..catalogue import service_names

    return {
        "services": ", ".join(service_names()),
        "sources": ", ".join(SOURCES),
        "stages": ", ".join(STAGES),
        "catalogue": catalogue_text(),
        "internal_domain": get_settings().internal_domain,
    }
