"""The ``shortlist`` node — deterministic code, and the node this design rests on.

No model, no threshold, no judgement. It sits where CARE has ``triage`` and it
exists because **a recommendation has two ways of being wrong that a
groundedness check cannot see**, and both are decidable in code.

## Three exits

**``compose``** — candidates survived the stated constraints, and only those
candidates are passed forward. The composer never sees a rejected one, because a
model shown eleven products and told to use four will use five.

**``no_match``** — nothing fits, *and the evidence is wide enough to say so*.

**``escalate``** — nothing fits, and the evidence is **not** wide enough.

That third exit is the one to read twice.

> **"We do not sell that" is a claim about the entire store, and it is only safe
> when the evidence covers the entire store.**

A cold index, a half-finished first sync, an adapter that timed out, a tenant
whose catalogue was never crawled — every one produces an empty candidate set
that is *indistinguishable, at this node, from a store that genuinely does not
stock the item*. Collapsing the two tells a shopper that a fully stocked store
is bare. So `no_match` requires a **successful catalogue lookup that returned
something**: proof the store was actually asked and actually answered. Anything
else escalates, naming which half failed.

This is `verify`'s fail-closed rule applied one node earlier — a missing verdict
reads as *not established*, never as *no objection raised*.

## The fabrication check

Every product id the composer may cite is recorded here, in
``state["promises"]``. `compose` is given only these, and a citation to anything
else is a fabrication — detectable by set membership rather than by a model
grading a model. It is what lets `shortlist_groundedness` be **gated at 1.00**
rather than judged, and it is *authorisation is code* (AGENTS.md rule 3)
applied to recommendation.

## What it does not do

**It does not rank.** Ordering candidates by fit would be a relevance judgement,
and a judgement made in code with no data behind it is a heuristic pretending to
be a rule. The catalogue's own order is preserved and the composer explains
each entry against the attributes it actually has. Ranking is a Stage-2 question
under the cold-start ramp ([blueprint §6](../../../../../docs/business/blueprint-v2.md))
and this scope contains nothing predictive on purpose (`sell.md` §5.3).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph import AgentState
from neura_agent_core.tools import ToolInvocation
from neura_core import get_logger

log = get_logger(__name__)

#: Entries in a shortlist. A shopper reading a chat window wants a choice, not a
#: catalogue, and a small model given ten candidates writes about all ten.
MAX_CANDIDATES = 4

#: Pulls `Product <id>: <title>` out of a rendered candidate — the shape
#: `tools/render.py` produces. Parsing our own renderer rather than passing
#: structures through the state keeps `AgentState` shared and agent-neutral; the
#: renderer and this pattern are two files that must agree, and a test pins them
#: together so they cannot drift silently.
_CANDIDATE = re.compile(r"^Product ([^\s:]+): (.+)$", re.MULTILINE)

#: A price line, as `_price_range` renders it: `24.00 GBP` or `18.00 GBP to 24.00 GBP`.
_PRICE = re.compile(r"price: ([\d.]+) ([A-Z]{3})")


async def shortlist(state: AgentState, config: RunnableConfig) -> AgentState:
    """Decide what may be recommended, or whether anything may be said at all."""
    successful = [i for i in state.get("invocations", []) if i.ok]
    catalogue_answered = any(
        i.tool_name in ("search_products", "get_product_details") for i in successful
    )

    candidates = _candidates(successful)
    surviving = _within_constraints(candidates, state)

    if surviving:
        log.info(
            "sell_shortlisted",
            conversation_id=state.get("conversation_id"),
            found=len(candidates),
            kept=len(surviving),
        )
        return {
            # The fabrication check's input. `compose` may cite these and
            # nothing else.
            "promises": [product_id for product_id, _ in surviving],
            "context": _evidence(successful, surviving),
        }

    if not catalogue_answered:
        # The store was never successfully asked. Saying "we do not carry that"
        # here would be a claim about a catalogue nobody read.
        log.info(
            "sell_no_catalogue_evidence",
            conversation_id=state.get("conversation_id"),
            tools=[i.tool_name for i in state.get("invocations", [])],
        )
        return {
            "escalated": True,
            "escalation_reason": (
                "the catalogue could not be searched, so whether this store carries "
                "it is unknown — not answered"
            ),
        }

    if not candidates:
        # The store answered and returned nothing. That is the honest miss.
        log.info("sell_no_match", conversation_id=state.get("conversation_id"))
        return {"promises": [], "context": _evidence(successful, [])}

    # The store answered, products came back, and the shopper's own constraints
    # excluded all of them. Also an honest miss — and a more useful one, because
    # `no_match` can say what was found and why it did not fit.
    log.info(
        "sell_all_candidates_excluded",
        conversation_id=state.get("conversation_id"),
        found=len(candidates),
    )
    return {"promises": [], "context": _evidence(successful, [])}


def reached_the_catalogue(state: AgentState) -> bool:
    """Was the store actually asked, and did it actually answer?

    The precondition on `no_match`, exposed for the graph's branch. A branch
    function cannot write state, so the decision is computed in the node and the
    branch only reads flags — but this predicate is the one the branch needs and
    it must be the same rule the node applied.
    """
    return any(
        i.ok and i.tool_name in ("search_products", "get_product_details")
        for i in state.get("invocations", [])
    )


def _candidates(invocations: list[ToolInvocation]) -> list[tuple[str, str]]:
    """Every product the catalogue actually returned, as `(id, rendered)`."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for invocation in invocations:
        if invocation.tool_name not in ("search_products", "get_product_details"):
            continue
        text = str(invocation.value)
        for match in _CANDIDATE.finditer(text):
            product_id = match.group(1)
            if product_id in seen:
                continue
            seen.add(product_id)
            found.append((product_id, _block(text, match.start())))

    return found


def _block(text: str, start: int) -> str:
    """One candidate's rendered block — from its header to the next one."""
    following = _CANDIDATE.search(text, start + 1)
    return text[start : following.start() if following else len(text)].strip()


def _within_constraints(
    candidates: list[tuple[str, str]], state: AgentState
) -> list[tuple[str, str]]:
    """Apply the shopper's own stated constraints. Nothing else.

    **A price ceiling is enforced here rather than described to the model**, and
    that is the difference between a constraint and a suggestion. "Under £150"
    is the one thing in a recommendation a shopper will check, and a model that
    includes a £180 jacket because it is otherwise perfect has produced the most
    embarrassing possible answer.

    Attributes are deliberately *not* filtered on here. Matching "waterproof"
    against a description is a language judgement, and doing it with a substring
    would drop a product described as "keeps the rain out". The composer is told
    to attribute its claims (open question **A9**); this node only enforces what
    is mechanically checkable.
    """
    ceiling = _ceiling(state)
    if ceiling is None:
        return candidates[:MAX_CANDIDATES]

    kept = [(pid, block) for pid, block in candidates if _cheapest(block, ceiling)]

    if len(kept) < len(candidates):
        log.info("sell_price_filtered", ceiling=str(ceiling), kept=len(kept))

    return kept[:MAX_CANDIDATES]


def _ceiling(state: AgentState) -> Decimal | None:
    raw = state.get("entities", {}).get("max_price")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        # A router that returned nonsense must not silently drop every candidate
        # — that would turn a bad extraction into "we sell nothing".
        log.warning("sell_unparsable_ceiling", value=raw)
        return None


def _cheapest(block: str, ceiling: Decimal) -> bool:
    """Does this product have *any* price at or below the ceiling?

    The lowest price wins, because a product ranging £120 to £200 does contain
    something a shopper with £150 can buy. A product with no published price is
    **kept**: it may well fit, and excluding it would silently hide a merchant's
    own products because of a gap in their own data.
    """
    prices = [Decimal(amount) for amount, _ in _PRICE.findall(block)]
    return not prices or min(prices) <= ceiling


def _evidence(invocations: list[ToolInvocation], surviving: list[tuple[str, str]]) -> str:
    """What `compose` and `no_match` may draw on.

    When candidates survive, only their blocks — the composer cannot mention a
    rejected product because it never sees one. When none survive, the raw tool
    results, so `no_match` can render what the store *does* carry without a
    second lookup.
    """
    if surviving:
        return "\n\n".join(block for _, block in surviving)

    return "\n\n".join(
        f'<tool_result name="{i.tool_name}">\n{i.value}\n</tool_result>' for i in invocations
    )


__all__ = ["MAX_CANDIDATES", "reached_the_catalogue", "shortlist"]
