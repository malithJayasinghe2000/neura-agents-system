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
from neura_agent_core.graph import Runtime
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
        llm=llm,
        prompts=load_prompts(),
    )


__all__ = ["MAX_TOOL_CALLS", "build_runtime"]
