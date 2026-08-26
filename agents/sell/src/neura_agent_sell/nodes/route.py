"""The ``route`` node — which of SELL's two intents is this, and what constrains it?

Runs on the ``ROUTER`` role: the cheapest model in the map, because this is a
classification with four answers plus a couple of short extractions. Not using
the reasoner here is most of what makes the local tier affordable
(llm-abstraction.md §9).

**Four things come out, and the last two are what make SELL different from CARE.**

* **the intent** — `recommend` or `compare`, or one of the two non-answers;
* **a self-contained need statement**, with every pronoun resolved. CARE's 1.9
  measurement applies unchanged: "what colours does it come in?" retrieves the
  *Payment Policy*, because "it" refers to a previous turn and a vector has no
  previous turn;
* **the constraints** — a price ceiling and required attributes. These are what
  `shortlist` filters on, and extracting them here means one model call does it
  once rather than three nodes each half-guessing;
* **the named candidates**, for `compare`.

**Two intents rather than CARE's three, and one fewer than it looks.** CARE's
router had to distinguish order status from product Q&A from policy; SELL's only
real question is whether the shopper has named products or described a need.
That is an easier classification, and the confidence bars are inherited from
CARE unchanged rather than re-derived — including the higher bar on declining
(open question **A5**, resolved there, and not re-opened here).
"""

from __future__ import annotations

from typing import Literal, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from neura_agent_core.graph import AgentState, Runtime, infra_error, runtime_of
from neura_core import get_logger
from neura_llm import ChatRequest, Message, ModelRole

log = get_logger(__name__)

PROMPT_NAME = "route"

RECOMMEND = "recommend"
COMPARE = "compare"
NEEDS_PERSON = "needs_person"
OUT_OF_SCOPE = "out_of_scope"

#: Below this, hand over rather than guess. Inherited from CARE, including its
#: reasoning: over-escalating costs a colleague a minute, under-escalating tells
#: a shopper something wrong about their money. **An informed starting point,
#: not a measurement** — the number most likely to move once real conversations
#: exist (**E3**), and moving it is a gated behaviour change like any other.
MIN_CONFIDENCE = 0.5

#: The bar for *declining* — ending a turn with neither an answer nor a person.
#: Higher than :data:`MIN_CONFIDENCE` for CARE's reason, which holds here
#: unchanged: `decline` is the one path an attacker gains from, because a
#: message that gets itself classified out-of-scope is answered with a polite
#: nothing and no security event reaches the merchant.
DECLINE_MIN_CONFIDENCE = 0.8

#: How many previous turns the router sees. Enough to resolve "the second one";
#: short enough that a long conversation cannot push the current message out of
#: a small model's context window.
HISTORY_TURNS = 4

#: A cap on extracted attributes. The list comes from a model, and an unbounded
#: one is a way to make `shortlist` filter a catalogue against forty predicates.
MAX_ATTRIBUTES = 6


class Route(BaseModel):
    """What the router is asked for. Small on purpose.

    A small model asked for a paragraph of reasoning gives a paragraph of
    reasoning and a worse classification; asked for an enum, a number and two
    short lists, it gives something usable.
    """

    intent: Literal["recommend", "compare", "needs_person", "out_of_scope"] = Field(
        description=(
            "recommend if the shopper describes a need without naming products; "
            "compare if they name two or more products; needs_person if this "
            "requires someone to act, concerns an existing order, or asks about "
            "returns or delivery policy; out_of_scope if it has nothing to do "
            "with shopping at this store."
        )
    )
    confidence: float = Field(ge=0.0, le=1.0, description="How sure you are of the intent.")
    need: str = Field(
        default="",
        description=(
            "A self-contained restatement of what the shopper is looking for, with "
            "every pronoun and reference to an earlier turn resolved. Used to search "
            "the catalogue on its own."
        ),
    )
    max_price: float | None = Field(
        default=None,
        description=(
            "A price ceiling the shopper stated, as a number with no currency symbol. "
            "Null unless they actually named one."
        ),
    )
    required_attributes: list[str] = Field(
        default_factory=list,
        description=(
            "Attributes the product must have, as short lowercase phrases the shopper "
            "used — e.g. ['waterproof', 'uk 9']. Empty if they stated none."
        ),
    )
    named_products: list[str] = Field(
        default_factory=list,
        description="Products the shopper named, verbatim. Empty unless intent is compare.",
    )


async def route(state: AgentState, config: RunnableConfig) -> AgentState:
    """Classify the turn and extract what later steps need."""
    runtime = runtime_of(config or {})
    message = state.get("message", "").strip()

    if not message:
        return _escalate("the shopper's message was empty")

    try:
        result = await _classify(runtime, message, state.get("history", []))
    except Exception as exc:
        # A wrong guess here misroutes the whole turn, and every step after it
        # inherits the mistake while appearing to work.
        log.warning("route_failed", conversation_id=state.get("conversation_id"), error=str(exc))
        return {
            **_escalate(f"routing could not be completed: {type(exc).__name__}"),
            **infra_error(exc, "the router was unreachable"),
        }

    update: AgentState = {
        "intent": result.intent,
        "intent_confidence": result.confidence,
        "entities": _entities(result),
        # Falls back to the message: a router returning an empty rewrite must not
        # silently disable retrieval for the turn.
        "search_query": result.need.strip() or message,
    }

    log.info(
        "sell_routed",
        conversation_id=state.get("conversation_id"),
        intent=result.intent,
        confidence=round(result.confidence, 2),
        constrained=bool(result.max_price or result.required_attributes),
    )

    if result.intent == NEEDS_PERSON:
        # SELL has no order tools, no policy tools and nothing that can change
        # anything, so a large class of ordinary shopper question ends here.
        # Named as a cost in `sell.md` §10 rather than hidden — and there is no
        # handoff to CARE, because agents may not import each other and the
        # event bus is Phase 3 (open question A13).
        return {**update, **_escalate("the question needs a person, or another agent")}

    if result.intent == OUT_OF_SCOPE:
        if result.confidence < DECLINE_MIN_CONFIDENCE:
            return {
                **update,
                **_escalate(
                    f"declined with confidence {result.confidence:.2f}, below the "
                    f"{DECLINE_MIN_CONFIDENCE} required to close a turn without a person"
                ),
            }
        log.info("sell_declined", conversation_id=state.get("conversation_id"))
        return update

    if result.confidence < MIN_CONFIDENCE:
        return {
            **update,
            **_escalate(f"routing confidence {result.confidence:.2f} is below {MIN_CONFIDENCE}"),
        }

    return update


async def _classify(runtime: Runtime, message: str, history: list[dict[str, str]]) -> Route:
    """One structured call on the ROUTER role."""
    request = ChatRequest(
        messages=[
            Message.system(runtime.prompt(PROMPT_NAME)),
            Message.user(_render(message, history)),
        ],
        temperature=0.0,
    )
    result = await runtime.llm.chat_structured(ModelRole.ROUTER, request, Route)
    return cast(Route, result.value)


def _render(message: str, history: list[dict[str, str]]) -> str:
    """The message and its recent context, delimited as untrusted.

    The delimiter does not make the content safe — a shopper can type the
    closing tag too. It makes the boundary *visible*: to a human reading the
    trace, and to the model, whose prompt says everything inside is material to
    classify rather than instructions to follow (security-model.md §2.3).
    """
    parts = []

    if recent := history[-HISTORY_TURNS:]:
        rendered = "\n".join(
            f"{turn.get('role', '?')}: {turn.get('content', '')}" for turn in recent
        )
        parts.append(f"<untrusted_previous_turns>\n{rendered}\n</untrusted_previous_turns>")

    parts.append(f"<untrusted_customer_message>\n{message}\n</untrusted_customer_message>")
    return "\n\n".join(parts)


def _entities(result: Route) -> dict[str, str]:
    """Only what was actually extracted.

    Stored as strings because `AgentState.entities` is `dict[str, str]` and is
    checkpointed — a shared state key is not the place for one agent to invent
    its own value types.
    """
    entities: dict[str, str] = {}

    if result.max_price is not None:
        entities["max_price"] = str(result.max_price)

    if attributes := [a.strip().lower() for a in result.required_attributes if a.strip()]:
        entities["required_attributes"] = "|".join(attributes[:MAX_ATTRIBUTES])

    if named := [p.strip() for p in result.named_products if p.strip()]:
        entities["named_products"] = "|".join(named[:MAX_ATTRIBUTES])

    return entities


def _escalate(reason: str) -> AgentState:
    return {"escalated": True, "escalation_reason": reason}


__all__ = [
    "COMPARE",
    "DECLINE_MIN_CONFIDENCE",
    "HISTORY_TURNS",
    "MIN_CONFIDENCE",
    "NEEDS_PERSON",
    "OUT_OF_SCOPE",
    "RECOMMEND",
    "Route",
    "route",
]
