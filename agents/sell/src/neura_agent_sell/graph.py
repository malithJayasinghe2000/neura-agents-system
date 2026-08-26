"""SELL's state machine.

    guard ─► route ─► retrieve ─► plan ─► act ─► shortlist ─► compose ─► verify ─► respond
      │        │ │                  │              │ │                     │
      │        │ └► decline         └► escalate    │ └► no_match           └► escalate
      │        └► escalate                         └► escalate
      └► blocked

Read the branches as the interesting part. Each is a different way a turn stops
being a recommendation:

* **route** — the router is unsure, the question needs a person, or it needs
  another agent SELL cannot reach. Caught before a lookup or an embedding is
  paid for.
* **plan** — the reasoner could not be reached at all.
* **shortlist** — the catalogue was never successfully searched, so whether this
  store carries the thing is *unknown* rather than *no*. See below.
* **verify** — the draft claims something the evidence does not support.

Two branches do **not** lead to a person, and both are deliberate:

* ``decline`` — out of scope, nobody needed. "What's the weather?" ends with a
  fixed message and no handoff. CARE's A5 resolution, inherited.
* ``no_match`` — the store genuinely does not carry it. A fixed message plus the
  store's own category list, and no model call anywhere in it.

Seven of the thirteen nodes are supplied by SELL; six are inherited from
``neura-agent-core``, which never learns this agent's name.

## The branch that carries the product

``shortlist`` has three exits, and the third is why the node exists.

> **"We do not sell that" is a claim about the entire store, and it is only safe
> when the evidence covers the entire store.**

A cold index, a half-finished sync or a timed-out adapter produces an empty
candidate set indistinguishable from a store that genuinely does not stock the
item. So ``no_match`` is reachable only when the catalogue was actually searched
and actually answered; anything else escalates, naming which half failed.

The decision is made **in the node**, not in the branch, for the reason CARE's
``triage`` exists: a LangGraph branch chooses an edge but cannot write state, so
an escalation decided in a branch arrives at the handoff with no reason attached
— and a support person picking that up has to reconstruct why.

## What ``guard`` is, and what it is not

Deterministic code: named rules over the shopper's text plus reversible PII
tokenisation. No model, no score, no threshold (ADR-0011).

**It is not the defence against prompt injection and must never be credited as
one.** SELL's position is CARE's: a shopper *can* persuade the model; what they
cannot do is make a persuaded model achieve anything. There is no tool that
changes a store, every proposal is authorised by code the model does not run,
and — specific to this agent — **a persuaded composer still cannot name a
product the catalogue did not return**, because ``respond`` checks the draft
against ``shortlist``'s own list before a shopper sees a word of it.

Injection resistance is measured against the policy engine's record, not against
the reply text, and ``make eval-guard-off`` must still report 1.00.
"""

from __future__ import annotations

from typing import Any

from neura_agent_core.graph import AgentGraph, AgentState
from neura_agent_sell.nodes import (
    OUT_OF_SCOPE,
    compose,
    decline,
    no_match,
    plan,
    reached_the_catalogue,
    respond,
    route,
    shortlist,
)

GUARD = "guard"
BLOCKED = "blocked"
ROUTE = "route"
RETRIEVE = "retrieve"
PLAN = "plan"
ACT = "act"
SHORTLIST = "shortlist"
DECLINE = "decline"
NO_MATCH = "no_match"
COMPOSE = "compose"
VERIFY = "verify"
RESPOND = "respond"
ESCALATE = "escalate"


def build_graph() -> AgentGraph:
    """Assemble SELL's graph. Not compiled — the caller supplies a checkpointer.

    Returning the builder keeps the checkpointer decision with whoever owns the
    database session: a served conversation checkpoints, an eval case does not
    need to and should not pay for it.
    """
    return (
        AgentGraph()
        .node(ROUTE, route)
        .node(PLAN, plan)
        .node(SHORTLIST, shortlist)
        .node(COMPOSE, compose)
        .node(RESPOND, respond)
        .node(DECLINE, decline)
        .node(NO_MATCH, no_match)
        # `guard` is the entry, and the builder enforces that rather than
        # trusting this line: redacting personal data after the router has read
        # the message is redaction of something already disclosed.
        .entry(GUARD)
        .branch(GUARD, _after_guard, {ROUTE: ROUTE, BLOCKED: BLOCKED})
        .branch(ROUTE, _after_route, {RETRIEVE: RETRIEVE, DECLINE: DECLINE, ESCALATE: ESCALATE})
        .edge(RETRIEVE, PLAN)
        .branch(PLAN, _after_plan, {ACT: ACT, ESCALATE: ESCALATE})
        .edge(ACT, SHORTLIST)
        .branch(
            SHORTLIST,
            _after_shortlist,
            {COMPOSE: COMPOSE, NO_MATCH: NO_MATCH, ESCALATE: ESCALATE},
        )
        .edge(COMPOSE, VERIFY)
        .branch(VERIFY, _after_verify, {RESPOND: RESPOND, ESCALATE: ESCALATE})
    )


def compile_graph(checkpointer: Any = None) -> Any:
    """NEURA-SELL, ready to run."""
    return build_graph().compile(checkpointer)


# ── Branches ─────────────────────────────────────────────────────────────────
#
# Plain functions of the state. "Why did it escalate?" should be answerable by
# reading five lines, and each of these is one condition with a name.


def _after_guard(state: AgentState) -> str:
    """One condition, and it is a fact rather than a judgement.

    ``blocked`` is set only when a *named* rule matched (ADR-0011); there is no
    score here to compare against a threshold and therefore no branch to get
    subtly wrong.
    """
    return BLOCKED if state.get("blocked") else ROUTE


def _after_route(state: AgentState) -> str:
    """Three ways out of routing, not two.

    ``decline`` is reached only when ``route`` positively decided the question
    is unrelated to shopping here *and* was confident enough to close a turn
    without a person. Everything unclear escalates.
    """
    if state.get("escalated"):
        return ESCALATE
    if state.get("intent") == OUT_OF_SCOPE:
        return DECLINE
    return RETRIEVE


def _after_plan(state: AgentState) -> str:
    return ESCALATE if state.get("escalated") else ACT


def _after_shortlist(state: AgentState) -> str:
    """The branch that carries the product's central claim.

    Three exits, and the order of the tests is load-bearing. ``escalated`` is
    checked **first**, so a turn the node decided it could not answer honestly
    cannot fall through to ``no_match`` — which would tell a shopper that a
    fully stocked store is bare.

    ``reached_the_catalogue`` is asserted again here rather than trusted. The
    node already refuses to leave ``escalated`` unset in that case, so this is
    redundant today; it is the line that keeps the claim true if somebody later
    adds a path into this branch that does not go through the node's own
    reasoning.
    """
    if state.get("escalated"):
        return ESCALATE
    if state.get("promises"):
        return COMPOSE
    if not reached_the_catalogue(state):
        return ESCALATE
    return NO_MATCH


def _after_verify(state: AgentState) -> str:
    """The last gate. Anything other than an explicit pass hands over.

    The test is on ``grounded`` being true, not on ``escalated`` being false:
    ``verify`` fails closed, and a missing verdict — the verifier timed out,
    returned nonsense, was never configured — must read as "not verified" rather
    than as "no objection raised".
    """
    return RESPOND if state.get("grounded") else ESCALATE


__all__ = ["build_graph", "compile_graph"]
