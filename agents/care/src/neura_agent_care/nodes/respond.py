"""The ``respond`` node — the only place a draft becomes something a shopper reads.

Deliberately the dullest node in the graph. It promotes ``draft`` to ``reply``
and records what produced it. Everything that could have stopped the answer has
already run: ``act`` authorised the lookups, ``verify`` checked the claims, and
the graph builder refuses to compile a shape where this node is reachable
without crossing ``verify`` (ADR-0004).

**It re-checks the verdict anyway.** One line, guarding against a future edit
that adds a path here — the builder's walk catches an unverified *route*, this
catches an unverified *state*, and they fail for different reasons. Neither is
redundant with the other, and the cost of the second is a conditional.

The prompt revision is stamped on the turn here. Six weeks after a shopper
complains, "which prompt wrote this?" needs an exact answer, and the only moment
it can be recorded honestly is the moment the words are committed to
(agent-runtime.md §8).

Not done here, and deliberately: PII rehydration. Redaction and its inverse are
milestone 1.12, and the seam is this node.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_care.prompts import REVISION
from neura_agent_core.graph import AgentState, runtime_of
from neura_core import get_logger

log = get_logger(__name__)


async def respond(state: AgentState, config: RunnableConfig) -> AgentState:
    """Send the verified draft."""
    runtime_of(config or {})  # the turn has a runtime, or nothing here is trustworthy

    draft = state.get("draft", "").strip()

    if not state.get("grounded") or not draft:
        # Unreachable through the compiled graph. Kept because "unreachable"
        # is a property of today's edges, and the edge that breaks it will be
        # added by someone who is not thinking about this file.
        log.error(
            "respond_without_verification",
            conversation_id=state.get("conversation_id"),
            grounded=state.get("grounded"),
        )
        return {
            "escalated": True,
            "escalation_reason": "respond was reached without a verified draft",
        }

    log.info(
        "responded",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
        intent=state.get("intent"),
        prompt_revision=REVISION,
        tools_used=[i.tool_name for i in state.get("invocations", []) if i.ok],
        sources=state.get("sources", []),
    )

    usage = dict(state.get("usage", {}))
    usage["prompt_revision"] = REVISION

    return {"reply": draft, "usage": usage}
