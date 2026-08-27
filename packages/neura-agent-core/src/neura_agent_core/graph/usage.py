"""What a turn spent — counted where the spending happens.

Every model call in the system passes through one of a handful of nodes, and
until 2026-08-27 exactly **one** of them counted anything: ``compose``. So the
figure a turn reported was the cost of writing the reply, and the router that
classified it, the planner that chose the lookups and the verifier that checked
the draft were all free.

**That is not a rounding error, it is the wrong half.** SELL's first eval run
recorded 3,048 tokens over fourteen cases — and eleven of those cases recorded
**zero**, because they escalated, declined or were blocked before ``compose``
ran. Every one of them had already called the router; four had called the
planner as well. A turn that ends at ``verify`` costs three model calls and was
booked as none.

The consequence is the question the role map exists to answer becoming
unanswerable: *what would this workload cost on a cloud provider?* The undercount
is not uniform — it is biased towards exactly the turns that end early, which is
where the local reasoner's weakness sends them. Modelling a cloud bill from it
would understate the cheap turns and misprice the expensive ones in opposite
directions.

## Why this lives in core rather than in each node

It was written once per composer, in SELL and in CARE, as a private ``_usage``
helper — and the nodes that did not have one simply did not count. A shared
accumulator makes forgetting visible: a node that calls a model and does not
call :func:`accrue` is a node with no usage line in its return.

## What is recorded, and why each field is here

``prompt_tokens`` and ``completion_tokens`` separately, because cloud providers
price them differently and a total cannot be converted back into a bill.
``by_role`` because the swap the role map exists for is per-role: *"what would a
cloud model in the GUARD role cost?"* is a question about ``verify``'s share
alone, and it is the question [ADR-0025](../architecture/adr/) is parked on.
``structured_repairs`` because a rising repair rate is the early warning that a
model is a bad fit for a role — the harness gates on it, and it was reading 0.00
from nothing at all.

**Cost is a string, not a float.** The amounts are small enough that a float
rounds them plausibly rather than visibly, and this dict is checkpointed to
Postgres and read back — a string survives that round trip without a JSON
encoder choosing a representation for us.

**Cost is zero for a local model and zero for an unpriced cloud model.** Those
are different facts and nothing here can tell them apart, which is why
``PriceTable`` logs the unknown model and the console prints *"not priced"*
rather than ``$0.00`` (CLAUDE.md §4). Set ``LLM_PRICING_JSON`` before quoting a
figure from this.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from neura_agent_core.graph.state import AgentState
from neura_llm import ChatResponse, ModelRole

#: Keys ``accrue`` owns. Anything else in ``usage`` — ``prompt_revision``, set by
#: ``respond`` — is carried through untouched.
TOTALS = ("calls", "prompt_tokens", "completion_tokens", "tokens", "structured_repairs")


def accrue(state: AgentState, role: ModelRole, response: ChatResponse) -> dict[str, Any]:
    """One model call, added to the turn's running total.

    Merged by the caller as the node's ``usage`` update::

        return {"draft": draft, "usage": accrue(state, ModelRole.REASONER, response)}

    For a structured call, pass ``result.response``: ``generate_structured``
    already folds every repair attempt's tokens and cost into it, so a turn that
    needed three attempts is charged for three.
    """
    usage = dict(state.get("usage", {}))

    usage["calls"] = int(usage.get("calls", 0)) + 1
    usage["prompt_tokens"] = int(usage.get("prompt_tokens", 0)) + response.usage.prompt_tokens
    usage["completion_tokens"] = (
        int(usage.get("completion_tokens", 0)) + response.usage.completion_tokens
    )
    usage["tokens"] = int(usage.get("tokens", 0)) + response.usage.total_tokens
    usage["structured_repairs"] = (
        int(usage.get("structured_repairs", 0)) + response.structured_repairs
    )
    usage["cost_usd"] = str(Decimal(str(usage.get("cost_usd", "0"))) + response.cost_usd)

    by_role: dict[str, dict[str, Any]] = {
        name: dict(entry) for name, entry in usage.get("by_role", {}).items()
    }
    entry = by_role.setdefault(
        role.value,
        {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": "0", "model": ""},
    )
    entry["calls"] = int(entry["calls"]) + 1
    entry["prompt_tokens"] = int(entry["prompt_tokens"]) + response.usage.prompt_tokens
    entry["completion_tokens"] = int(entry["completion_tokens"]) + response.usage.completion_tokens
    entry["cost_usd"] = str(Decimal(str(entry["cost_usd"])) + response.cost_usd)
    # The model that actually served the role. Recorded because a token count
    # without it cannot be repriced against a different provider later, which is
    # the entire use of keeping local usage data (llm-abstraction.md §3).
    entry["model"] = response.model or entry["model"]
    usage["by_role"] = by_role

    return usage


def total_tokens(usage: dict[str, Any]) -> int:
    """Every token the turn spent, in any role."""
    return int(usage.get("tokens", 0))


def total_cost(usage: dict[str, Any]) -> Decimal:
    """What the turn cost. ``0`` for local models **and** for unpriced ones."""
    return Decimal(str(usage.get("cost_usd", "0")))


__all__ = ["TOTALS", "accrue", "total_cost", "total_tokens"]
