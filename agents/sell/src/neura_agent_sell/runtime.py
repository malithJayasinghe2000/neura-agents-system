"""Assembling everything one SELL conversation needs.

The graph describes the flow; this describes the equipment. A turn needs a tool
registry, a policy engine over it, the store connection, an LLM client, the
prompts, a budget, and — optionally — a retriever.

A single function on purpose. Every caller that runs SELL goes through it: the
API, the eval target, any smoke script. Three places assembling a runtime by
hand is three places for one of them to be configured slightly differently, and
the version that goes wrong quietly is the one where a scope is missing and the
agent simply stops calling tools.

**The ``ToolContext`` is the security boundary's input, and none of it comes
from the model.** The tenant, the store, the capabilities, the key's scopes and
what the session has *proven* all arrive from the authenticated request. No
prompt can alter any of them, which is what makes AGENTS.md rule 3 true in
practice rather than in principle.
"""

from __future__ import annotations

from typing import Any

from neura_agent_core.audit import AuditSink
from neura_agent_core.graph import Runtime, guard_enabled_by_default
from neura_agent_core.policy import ConversationBudget, PolicyEngine
from neura_agent_core.rag.retrieval import Retriever
from neura_agent_core.tools import SessionIdentity, ToolContext
from neura_agent_sell.prompts import load_prompts
from neura_agent_sell.tools import build_registry
from neura_domain import Capability

#: The tool-call ceiling for one turn.
#:
#: Four, matching CARE, and inherited rather than re-derived — open question
#: **A3** is unresolved for both agents and tuning it is an eval-gated change.
#: Enough for "search, then confirm stock on the two that fit", and short enough
#: that a small model looping on the same call becomes an escalation in seconds
#: rather than a burned budget.
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
    configuration here. A store that reports no live inventory feed never shows
    ``check_stock`` to the model for that tenant — the tool does not exist as
    far as the conversation is concerned.

    ``identity`` defaults to an anonymous session, the only safe default for an
    access-control value. **SELL has no session-scoped tool today**, so nothing
    depends on it — and that is exactly why the default must stay anonymous: the
    first tool that does depend on it must inherit "has proven nothing".

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
        guard_enabled=guard_enabled_by_default() if guard_enabled is None else guard_enabled,
        # `vault` is deliberately not a parameter: every turn starts with a
        # fresh, empty redaction map, and a caller able to pass one in is a
        # caller able to share one between two shoppers by accident.
    )


__all__ = ["MAX_TOOL_CALLS", "build_runtime"]
