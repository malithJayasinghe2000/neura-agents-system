"""CARE's state machine.

    route ─► retrieve ─► plan ─► act ─► triage ─► compose ─► verify ─► respond
      │ │                  │              │                    │
      │ └► decline         └──────────────┴────────────────────┴──────► escalate
      └────────────────────────────────────────────────────────────────►

Read the branches as the interesting part. Most lead to ``escalate``, and each is
a different way a turn can stop being answerable:

* **route** — the router is not confident, or the question is out of scope *and*
  needs a person. Caught before a single lookup or embedding is paid for.
* **plan** — the reasoner could not be reached at all.
* **triage** — the policy engine refused on ownership, or the model called
  ``escalate_to_human`` because the shopper asked for a person.
* **verify** — the draft claims something the evidence does not support.

``decline`` is the exception, and the newest node here. An out-of-scope question
that needs no person — "what's the weather?" — ends there instead, with a fixed
message and no handoff. Resolves open question A5; the reasoning is in
``nodes/decline.py``, including why that node may skip ``verify``.

Four of the ten nodes are inherited unchanged from ``neura-agent-core``. CARE
supplies ``route``, ``plan``, ``triage``, ``compose``, ``respond`` and
``decline``; the engine supplies ``retrieve``, ``act``, ``verify`` and
``escalate``, and never learns this agent's name.

## A known deviation: there is no `act → act` loop

`agent-runtime.md §2` specifies `act --> act: another tool needed (max 4)`. This
graph is single-pass: the planner chooses tools once, they run, and the composer
writes from whatever came back. The budget of four calls exists and is enforced,
but nothing routes back to ask for a second round.

**It is measured, not theoretical.** Two of the six remaining eval failures are
this and nothing else: a shopper asking whether a shoe comes in UK 9 needs
`search_products` *then* `get_product_details`, because the search result carries
no size-level stock. The agent answered from one call — and in one case it
answered *correctly*, which is worse, because the groundedness judge caught that
the correct answer was not supported by anything it had actually looked up.

Deliberately not fixed in 1.11 rather than fixed hastily: a loop changes latency,
cost and the failure modes of every turn, so it needs its own eval run to justify
rather than a plausible-looking edge. The single-pass version fails safe — it
escalates or admits it does not know.

## What is deliberately not here yet

``guard`` and ``blocked``. Injection detection and PII redaction are milestone
1.12 and need their own eval to be worth anything, so the nodes are absent rather
than present-and-empty — a ``guard`` node that returns "clean" would report as
protection while being none, which is the failure mode that concerns this project
most.

Their absence does not leave injection undefended, and it is worth being precise
about why. CARE's position is that a shopper *can* persuade the model; what they
cannot do is make a persuaded model achieve anything, because there is no tool
that changes a store to invoke, every proposal is authorised by code the model
does not run, and an unowned order reference escalates rather than answering
(security-model.md §2.1). Injection resistance is measured against the policy
engine's record, not against the reply text, and it is gated at 1.00 today.
"""

from __future__ import annotations

from typing import Any

from neura_agent_care.nodes import OUT_OF_SCOPE, compose, decline, plan, respond, route, triage
from neura_agent_core.graph import AgentGraph, AgentState

ROUTE = "route"
RETRIEVE = "retrieve"
PLAN = "plan"
ACT = "act"
TRIAGE = "triage"
DECLINE = "decline"
COMPOSE = "compose"
VERIFY = "verify"
RESPOND = "respond"
ESCALATE = "escalate"


def build_graph() -> AgentGraph:
    """Assemble CARE's graph. Not compiled — the caller supplies a checkpointer.

    Returning the builder rather than a compiled graph keeps the checkpointer
    decision with whoever owns the database session: a served conversation
    checkpoints to Postgres, an eval case does not need to and should not pay
    for it.
    """
    return (
        AgentGraph()
        .node(ROUTE, route)
        .node(PLAN, plan)
        .node(TRIAGE, triage)
        .node(COMPOSE, compose)
        .node(RESPOND, respond)
        .node(DECLINE, decline)
        .entry(ROUTE)
        .branch(ROUTE, _after_route, {RETRIEVE: RETRIEVE, DECLINE: DECLINE, ESCALATE: ESCALATE})
        .edge(RETRIEVE, PLAN)
        .branch(PLAN, _after_plan, {ACT: ACT, ESCALATE: ESCALATE})
        .edge(ACT, TRIAGE)
        .branch(TRIAGE, _after_triage, {COMPOSE: COMPOSE, ESCALATE: ESCALATE})
        .edge(COMPOSE, VERIFY)
        .branch(VERIFY, _after_verify, {RESPOND: RESPOND, ESCALATE: ESCALATE})
    )


def compile_graph(checkpointer: Any = None) -> Any:
    """CARE, ready to run."""
    return build_graph().compile(checkpointer)


# ── Branches ─────────────────────────────────────────────────────────────────
#
# Plain functions of the state, deliberately. "Why did it escalate?" should be
# answerable by reading five lines, and each of these is one condition with a
# name.


def _after_route(state: AgentState) -> str:
    """Three ways out of routing, not two.

    `decline` is the A5 outcome: out of scope, but no person is needed. It is a
    terminal node like `escalate`, and it is reached only when `route` has
    positively decided a human is unnecessary — `needs_human` defaults to True,
    so anything unclear hands over instead.
    """
    if state.get("escalated"):
        return ESCALATE
    if state.get("intent") == OUT_OF_SCOPE:
        return DECLINE
    return RETRIEVE


def _after_plan(state: AgentState) -> str:
    return ESCALATE if state.get("escalated") else ACT


def _after_triage(state: AgentState) -> str:
    """Escalate on a policy refusal, or because the shopper asked for a person.

    Two different reasons routed the same way on purpose. An escalation always
    takes one path and always produces the same handoff packet, whether it was
    forced by the ownership gate in ``act`` or chosen by a model calling
    ``escalate_to_human`` — one code path is one thing to get right.
    """
    return ESCALATE if state.get("escalated") else COMPOSE


def _after_verify(state: AgentState) -> str:
    """The last gate. Anything other than an explicit pass hands over.

    Note the test is on ``grounded`` being true, not on ``escalated`` being
    false: ``verify`` fails closed, and a missing verdict — the verifier timed
    out, returned nonsense, was never configured — must read as "not verified"
    rather than as "no objection raised".
    """
    return RESPOND if state.get("grounded") else ESCALATE


__all__ = ["build_graph", "compile_graph"]
