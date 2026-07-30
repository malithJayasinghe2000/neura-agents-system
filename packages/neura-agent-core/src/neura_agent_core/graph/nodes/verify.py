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

## The outbound PII check, which is not about groundedness

Added in milestone 1.12. Before the model is asked anything, the draft is scanned
for personal data that nothing in the turn accounts for — a payment card number,
or a contact detail appearing in neither the evidence nor the shopper's own words
(security-model.md §6.3, threat T10). A hit escalates.

It lives here rather than in an agent's `respond` for two reasons. It is the last
gate before an answer is committed to, which is where §6.3 puts it; and it is
deterministic, which matters more than it sounds. Hand-probing on 2026-07-29
measured this node's *model* verdict flipping from 0/30 to 30/30 refusals on the
same draft when a second, meaningless evidence block was added (open question
A8). A check that cannot be talked out of its answer is worth having beside one
that can.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from neura_agent_core.graph.state import AgentState, runtime_of
from neura_agent_core.guard import find_leaks
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

    evidence = evidence_of(state)

    # What a contact detail in the draft is allowed to have come from: the
    # evidence, or the shopper's own message.
    #
    # The message is in here for a reason that is easy to miss. With the guard
    # ON it contributes nothing — `guard` has already tokenised it, so there is
    # no address in it to match. With the guard OFF, for a `make eval-guard-off`
    # run, it is the *only* record that the shopper gave us their email, and
    # without it a turn that reads a customer's own address back to them would
    # escalate. A measurement mode has to differ from the real thing in exactly
    # one respect — whether attacks are recognised — or it is measuring a
    # different system and its 1.00 means nothing.
    accounted_for = f"{evidence}\n{state.get('message', '')}"

    if leaks := find_leaks(draft, evidence=accounted_for, vault=runtime.vault):
        # Escalate, do not scrub. A reply carrying personal data nothing
        # supports is not a good reply with one bad sentence in it — it is the
        # product of reasoning that went somewhere it should not have, and
        # editing out the symptom would send the rest of it anyway.
        reasons = [leak.detail for leak in leaks]
        log.error(
            "outbound_pii_blocked",
            conversation_id=state.get("conversation_id"),
            tenant_id=state.get("tenant_id"),
            kinds=[leak.kind for leak in leaks],
        )
        return {**_ungrounded(f"outbound PII check: {'; '.join(reasons)}"), "pii_leaks": reasons}

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


def evidence_of(state: AgentState) -> str:
    """Everything the draft is allowed to rely on.

    Retrieved context plus successful tool results. A *failed* tool call is
    deliberately excluded — "the store did not answer" supports no claim about
    an order, and treating it as evidence would let a draft invent one.

    Public, because ``respond``'s outbound PII filter has to ask the same
    question of the same text. Two definitions of "the evidence" is one too
    many: the moment they drift, a value is grounded for one check and a leak
    for the other.
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
