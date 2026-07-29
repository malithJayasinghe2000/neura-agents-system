"""The ``verify`` node — is every claim in the draft actually supported?

`agent-runtime.md §2` calls this **the single most valuable node**, and the
reason is worth restating: a confident wrong answer about someone's order or
someone's money is the worst thing this product can do. Escalating is always the
cheaper error.

So this node re-reads the draft against the evidence — retrieved chunks and tool
results — and asks whether each factual claim is supported. Unsupported means
escalate, not soften.

**Three properties it must have, each guarding a way this check could become
decorative:**

* **It runs on the ``GUARD`` role, never the composer.** A model checking its
  own work agrees with itself. This is the same reason the eval harness refuses
  to let a model judge itself (evaluation-strategy.md §3.1).
* **It fails closed.** If the verifier errors, times out, or returns something
  unparseable, the draft is *not* sent. A verification step that lets answers
  through when it breaks is worse than none, because it looks like protection.
* **An empty evidence set is not a pass.** A draft asserting facts with nothing
  retrieved and no tool called is precisely the hallucination case. The check is
  structural and happens before any model call.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from neura_agent_core.graph.state import AgentState, runtime_of
from neura_core import get_logger

log = get_logger(__name__)

PROMPT_NAME = "verify"

#: Replies that assert nothing about the world need no evidence. A refusal, a
#: clarifying question or a handover line cannot be ungrounded, and requiring
#: evidence for them would escalate every "could you tell me your order number?".
MAX_UNGROUNDED_CHARS = 400


class Groundedness(BaseModel):
    """What the guard model is asked for. Deliberately tiny.

    A small model asked for prose produces prose; asked for a boolean and one
    sentence, it produces a usable answer. The unsupported claim is requested by
    name because it is what a human reviewer needs in the escalation.
    """

    grounded: bool = Field(description="Is every factual claim supported by the evidence?")
    unsupported_claim: str = Field(
        default="", description="The first unsupported claim, quoted. Empty if grounded."
    )


async def verify(state: AgentState, config: RunnableConfig) -> AgentState:
    """Check the draft against the evidence. Fails closed."""
    runtime = runtime_of(config or {})
    draft = state.get("draft", "").strip()

    if not draft:
        return _ungrounded("there is no draft to verify")

    evidence = _evidence(state)

    if not evidence:
        # Structural, before any model call. A reply with no evidence behind it
        # is either harmless conversation or a hallucination, and length is a
        # crude but honest separator — a long confident answer grounded in
        # nothing is the exact failure this node exists for.
        if len(draft) <= MAX_UNGROUNDED_CHARS:
            return {"grounded": True, "verify_reason": "no factual claims to support"}
        return _ungrounded("the draft makes claims but nothing was retrieved and no tool ran")

    if runtime.llm is None:
        return _ungrounded("no verifier is configured")

    try:
        result = await _ask(runtime, draft, evidence)
    except Exception as exc:
        # Fails closed. A verifier that lets answers through when it breaks is
        # worse than no verifier, because it looks like protection.
        log.warning("verify_failed", conversation_id=state.get("conversation_id"), error=str(exc))
        return _ungrounded(f"verification could not be completed: {type(exc).__name__}")

    if result.grounded:
        log.info("verify_passed", conversation_id=state.get("conversation_id"))
        return {"grounded": True, "verify_reason": "every claim supported"}

    return _ungrounded(f"unsupported claim: {result.unsupported_claim or 'unspecified'}")


async def _ask(runtime: Any, draft: str, evidence: str) -> Groundedness:
    """One structured call on the GUARD role."""
    from neura_llm import ChatRequest, Message, ModelRole

    request = ChatRequest(
        messages=[
            Message.system(runtime.prompt(PROMPT_NAME)),
            Message.user(f"EVIDENCE:\n{evidence}\n\nDRAFT REPLY:\n{draft}"),
        ],
        temperature=0.0,
    )
    result = await runtime.llm.chat_structured(ModelRole.GUARD, request, Groundedness)
    return cast(Groundedness, result.value)


def _evidence(state: AgentState) -> str:
    """Everything the draft is allowed to rely on.

    Retrieved context plus successful tool results. A *failed* tool call is
    deliberately excluded — "the store did not answer" supports no claim about
    an order, and treating it as evidence would let a draft invent one.
    """
    parts: list[str] = []

    context = state.get("context", "")
    if context:
        parts.append(context)

    for invocation in state.get("invocations", []):
        if invocation.ok:
            parts.append(
                f'<tool_result name="{invocation.tool_name}">\n{invocation.value}\n</tool_result>'
            )

    return "\n\n".join(parts)


def _ungrounded(reason: str) -> AgentState:
    return {
        "grounded": False,
        "verify_reason": reason,
        "escalated": True,
        "escalation_reason": reason,
    }
