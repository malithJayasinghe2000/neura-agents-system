"""The ``no_match`` node — telling a shopper this store does not carry it.

The honest miss, and the reason `shortlist` exists. A terminal node like
``decline``, with the same exemption from ``verify`` and a sharper reason for it.

## Why this may not be a generation

An agent asked to break bad news gently will, often enough to matter, offer the
nearest thing and imply it fits. That single sentence is the most common failure
mode of every recommender ever shipped, and it is one word away from the
sentence a shopper acts on with their money.

So there is no model call here at all. The reply is a fixed file, plus — where
the store declared ``CATEGORY_READ`` — a list of categories rendered
deterministically from what the catalogue actually returned. **Nothing in this
reply is a claim a model composed**, so there is no ungrounded statement for
``verify`` to catch and nothing for it to do.

## What it may and may not say

**May:** the fixed sentence; the categories this store publishes; an offer to
pass the shopper to a person.

**May not:** name a near-miss product as though it fits, describe what was
found, or explain *why* the store does not carry something. The first is the
failure above. The second is a shortlist by another name. The third is a claim
about a merchant's buying decisions that nothing in this system knows.

## The precondition, which is not enforced here

This node is only reachable when `shortlist` established that the catalogue was
actually searched and actually answered. **That check lives in `shortlist`,
before the branch**, because a branch function cannot write state and an
escalation arriving with no reason attached is one a support person has to
reconstruct. If this node is ever reached another way, it will confidently tell
a shopper that a fully stocked store is bare — which is why the branch is one
line and the reasoning is all in `shortlist`.
"""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph import AgentState, runtime_of
from neura_core import get_logger

log = get_logger(__name__)

PROMPT_NAME = "no_match"

#: The line `tools/render.py` writes for `list_categories`.
_CATEGORIES = re.compile(r"^This store's categories: (.+)$", re.MULTILINE)


async def no_match(state: AgentState, config: RunnableConfig) -> AgentState:
    """Say plainly that this store does not carry it."""
    runtime = runtime_of(config or {})

    reply = runtime.prompt(PROMPT_NAME)

    # Appended only when the store actually published a category list this turn.
    # Not fetched here, and not inferred: if `list_categories` did not run or
    # the store declares no `CATEGORY_READ`, the fixed sentence stands alone
    # (`sell.md` §3.3 names this as the degradation).
    if categories := _categories(state):
        reply = f"{reply}\n\n{categories}"

    log.info(
        "sell_no_match",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
        offered_categories=bool(categories),
    )

    return {
        "reply": reply,
        # Not an escalation and not a failure. The shopper got a true answer,
        # which is the whole point of this node existing rather than the turn
        # ending in a person or in a plausible substitute.
        "escalated": False,
        "refused": True,
        # Grounded by construction: a fixed file plus a list copied verbatim
        # from a tool result asserts nothing the store did not say.
        "grounded": True,
        "verify_reason": "a fixed miss message and the store's own category list",
    }


def _categories(state: AgentState) -> str:
    """The store's own category line, verbatim, or nothing.

    Copied rather than summarised — the merchant's own words are the only thing
    here that could be wrong, and copying them means they cannot be.
    """
    for invocation in state.get("invocations", []):
        if not (invocation.ok and invocation.tool_name == "list_categories"):
            continue
        if match := _CATEGORIES.search(str(invocation.value)):
            return f"This store does sell: {match.group(1)}."
    return ""


__all__ = ["PROMPT_NAME", "no_match"]
