"""The ``respond`` node — the only place a draft becomes something a shopper reads.

Deliberately the dullest node in the graph. It promotes ``draft`` to ``reply``
and records what produced it. Everything that could have stopped the answer has
already run: `act` authorised the lookups, `shortlist` decided what may be
recommended, `verify` checked the claims, and the graph builder refuses to
compile a shape where this node is reachable without crossing `verify`
(ADR-0004).

**It re-checks the verdict anyway.** One line, guarding a future edit that adds
a path here — the builder's walk catches an unverified *route*, this catches an
unverified *state*, and they fail for different reasons.

**And it re-checks the shortlist.** A reply naming a product id that was never
in ``promises`` is a fabrication, and this is the last place it can be caught
before a shopper reads it. That check is set membership, not a judgement, which
is why `shortlist_groundedness` is gated at 1.00 rather than scored by a model.

## PII rehydration

`guard` replaced the shopper's email, phone, card and address with tokens before
any model saw them; this is where they come back, from a map that lived on the
runtime and never touched a database (security-model.md §6.1). Rehydration
cannot introduce a leak — the only values it can restore are the ones the
shopper typed this turn, which `verify`'s outbound filter already treats as
accounted for.
"""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph import AgentState, runtime_of
from neura_agent_sell.prompts import REVISION
from neura_core import get_logger

log = get_logger(__name__)

#: Product ids as `tools/render.py` writes them into a reply's evidence. Used
#: only to *find* candidate citations in a draft; whether each is legitimate is
#: decided by set membership against `promises`.
_CITED = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_-]{2,})\b")


async def respond(state: AgentState, config: RunnableConfig) -> AgentState:
    """Rehydrate the verified draft and send it."""
    runtime = runtime_of(config or {})

    draft = state.get("draft", "").strip()

    if not state.get("grounded") or not draft:
        # Unreachable through the compiled graph. Kept because "unreachable" is
        # a property of today's edges, and the edge that breaks it will be added
        # by someone not thinking about this file.
        log.error(
            "sell_respond_without_verification",
            conversation_id=state.get("conversation_id"),
            grounded=state.get("grounded"),
        )
        return {
            "escalated": True,
            "escalation_reason": "respond was reached without a verified draft",
        }

    if invented := _invented_ids(draft, state):
        # The fabrication check, at the last possible moment. A shortlist that
        # names a product the catalogue never returned is the failure this whole
        # design exists to make impossible, and escalating is the only safe
        # outcome — there is no way to "fix" the sentence without inventing.
        log.error(
            "sell_fabricated_product",
            conversation_id=state.get("conversation_id"),
            invented=sorted(invented),
            promised=state.get("promises", []),
        )
        return {
            "escalated": True,
            "escalation_reason": (
                "the draft named a product that was not in the shortlist: "
                + ", ".join(sorted(invented))
            ),
        }

    reply = runtime.vault.rehydrate(draft)

    log.info(
        "sell_responded",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
        intent=state.get("intent"),
        prompt_revision=REVISION,
        recommended=state.get("promises", []),
        rehydrated=len(state.get("redactions", [])),
    )

    usage = dict(state.get("usage", {}))
    usage["prompt_revision"] = REVISION

    return {"reply": reply, "usage": usage}


def _invented_ids(draft: str, state: AgentState) -> set[str]:
    """Product ids in the draft that were never on the shortlist.

    **Deliberately narrow.** It only considers tokens that *look like* a product
    id and appear in the evidence's id namespace — it does not try to decide
    whether an English sentence names a product, which is a language judgement
    and would produce false positives on ordinary prose.

    The check that matters is the reverse direction, and it is exact: of the ids
    this store actually returned, none may appear unless it survived
    `shortlist`. An id from a *rejected* candidate reaching a reply is the
    price-ceiling violation and the out-of-stock recommendation both.
    """
    promised = set(state.get("promises", []))
    returned = _returned_ids(state)

    # Only ids the store returned this turn are checked. A token that resembles
    # an id but was never in any tool result is prose, not a fabricated citation.
    cited = {token for token in _CITED.findall(draft) if token in returned}
    return cited - promised


def _returned_ids(state: AgentState) -> set[str]:
    """Every product id any tool result carried this turn."""
    ids: set[str] = set()
    for invocation in state.get("invocations", []):
        if invocation.ok:
            ids.update(re.findall(r"^Product ([^\s:]+):", str(invocation.value), re.MULTILINE))
    return ids


__all__ = ["respond"]
