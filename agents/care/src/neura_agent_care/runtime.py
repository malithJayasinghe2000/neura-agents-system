"""Assembling everything one CARE conversation needs.

The graph describes the flow; this describes the equipment. A turn needs a tool
registry, a policy engine over it, the store connection, an LLM client, the
prompts, a budget, and — optionally — a retriever.

It is a single function on purpose. Every caller that runs CARE goes through it:
the API in milestone 1.14, the eval target, the smoke script. Three places
assembling a runtime by hand is three places for one of them to be configured
slightly differently, and the version that goes wrong quietly is the one where a
scope is missing and the agent simply stops calling tools.

**The ``ToolContext`` is the security boundary's input, and none of it comes from
the model.** The tenant, the store, the capabilities, the API key's scopes and
what the session has *proven* about the shopper all arrive from the
authenticated request. No prompt can alter any of them, which is what makes
AGENTS.md rule 3 true in practice rather than in principle.
"""

from __future__ import annotations

from typing import Any

from neura_agent_care.prompts import load_prompts
from neura_agent_care.tools import build_registry
from neura_agent_core.audit import AuditSink
from neura_agent_core.graph import Runtime, guard_enabled_by_default
from neura_agent_core.policy import ConversationBudget, PolicyEngine
from neura_agent_core.rag.retrieval import Retriever
from neura_agent_core.tools import SessionIdentity, ToolContext
from neura_domain import Capability

#: The tool-call ceiling for one turn.
#:
#: A guess, and recorded as one — open question A3, to be tuned from eval data
#: rather than argued about. Four is enough for "look up the order, then check
#: the returns policy" and short enough that a small model looping on the same
#: call becomes an escalation within seconds instead of a burned budget
#: (llm-abstraction.md §6).
MAX_TOOL_CALLS = 4


def build_runtime(
    *,
    tenant_id: str,
    conversation_id: str,
    adapter: Any,
    llm: Any,
    capabilities: frozenset[Capability],
    scopes: frozenset[str],
    identity: SessionIdentity | None = None,
    retriever: Retriever | None = None,
    audit: AuditSink | None = None,
    guard_enabled: bool | None = None,
    allowed_tools: frozenset[str] | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> Runtime:
    """One conversation's runtime.

    ``capabilities`` comes from the store's own ``/health`` response, not from
    configuration here. A store that cannot search orders declares so, and
    ``find_orders_for_customer`` is then never shown to the model for that
    tenant — the tool does not exist as far as the conversation is concerned.

    ``identity`` defaults to an anonymous session, which is the only safe
    default for an access-control value: a shopper who has proven nothing must
    start having proven nothing.

    ``audit`` is where `guard` writes a security event when it blocks a turn.
    It is optional so that a unit test can run the graph without a database —
    but **a block with no sink is a block nobody can count**, and countability
    is most of the argument for blocking rather than escalating (ADR-0012). A
    served conversation must pass a real one.

    ``guard_enabled`` defaults to whatever ``NEURA_GUARD_ENABLED`` says, which
    is on. Passing it explicitly is for measurement — ``make eval-guard-off``
    and the tests that prove the guard is not what makes injection resistance
    1.00 (ADR-0011). It is not a deployment switch.
    """
    ctx = ToolContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        capabilities=capabilities,
        scopes=scopes,
        identity=identity or SessionIdentity(),
        adapter=adapter,
        allowed_tools=allowed_tools,
    )

    registry = build_registry()

    return Runtime(
        ctx=ctx,
        registry=registry,
        policy=PolicyEngine(registry),
        budget=ConversationBudget(max_tool_calls=max_tool_calls),
        retriever=retriever,
        audit=audit,
        llm=llm,
        prompts=load_prompts(),
        # `None` means "whatever the environment says", which is on. Spelled out
        # rather than defaulted to `True` here, so that `NEURA_GUARD_ENABLED`
        # keeps working for callers that never think about the guard.
        guard_enabled=guard_enabled_by_default() if guard_enabled is None else guard_enabled,
        # `vault` is deliberately not a parameter: every turn starts with a
        # fresh, empty redaction map, and a caller able to pass one in is a
        # caller able to share one between two shoppers by accident.
    )


__all__ = ["MAX_TOOL_CALLS", "build_runtime"]
