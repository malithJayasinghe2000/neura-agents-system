"""The ``plan`` node — choosing which lookups to run.

The model proposes tool calls here; ``act`` authorises and executes them. Keeping
the two apart is the point of the split: proposing is a language task the model
is good at, authorising is a security decision it must have no part in. Nothing
this node returns is trusted — every proposal goes through all eight policy
checks before anything touches a store.

**Only the tools this conversation may actually use are offered.** The registry
filters by the store's declared capabilities before the definitions are built, so
a store with no live inventory feed produces a model that has never heard of
``check_stock``. That is stronger than refusing the call afterwards: you cannot
talk a model into invoking a tool it was never shown.

**Proposing nothing is a valid plan**, and a common one. Retrieval has already
run by this point, so a policy question is often answerable from the store's own
indexed text with no lookup at all. Forcing a call when none is needed spends a
shopper's latency and the merchant's budget on a round trip that adds nothing.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph import AgentState, infra_error, propose, runtime_of
from neura_core import get_logger
from neura_llm import ChatRequest, Message, ModelRole
from neura_llm import ToolSpec as LLMToolSpec

log = get_logger(__name__)

PROMPT_NAME = "plan"


async def plan(state: AgentState, config: RunnableConfig) -> AgentState:
    """Ask the reasoner which lookups would answer this question."""
    runtime = runtime_of(config or {})

    available = runtime.registry.available_for(runtime.ctx)
    if not available:
        # A real configuration, not a bug: a store that declares no capabilities
        # CARE can use. Said out loud rather than producing an empty plan that
        # looks like the model deciding it needed nothing.
        log.info("plan_no_tools", conversation_id=state.get("conversation_id"))
        return propose([])

    try:
        response = await runtime.llm.chat(
            ModelRole.REASONER,
            ChatRequest(
                messages=[
                    Message.system(runtime.prompt(PROMPT_NAME)),
                    Message.user(_render(state)),
                ],
                tools=[
                    LLMToolSpec(
                        name=spec.name,
                        description=spec.description,
                        parameters=spec.json_schema(),
                    )
                    for spec in available
                ],
                temperature=0.0,
            ),
        )
    except Exception as exc:
        # agent-runtime.md §2: an `act` failure escalates. Continuing to compose
        # with no evidence would produce a fluent answer built on nothing, which
        # `verify` would then have to catch — and relying on the last line of
        # defence for a failure we can see here is how the last line stops being
        # a defence.
        log.warning("plan_failed", conversation_id=state.get("conversation_id"), error=str(exc))
        return {
            "escalated": True,
            "escalation_reason": f"tool planning failed: {type(exc).__name__}",
            # A provider that is not there is not an agent decision. Recorded
            # separately so the eval skips this case instead of scoring it
            # (open question E6).
            **infra_error(exc, "the reasoner was unreachable while planning"),
        }

    proposals = [{"name": call.name, "arguments": call.arguments} for call in response.tool_calls]

    log.info(
        "planned",
        conversation_id=state.get("conversation_id"),
        proposed=[call.name for call in response.tool_calls],
        offered=[spec.name for spec in available],
    )
    return propose(proposals)


def _render(state: AgentState) -> str:
    """What the planner sees.

    Everything the router already worked out is passed on explicitly, rather than
    left for this model to re-derive from the raw message:

    * **The resolved question.** The router rewrites "what colours does it come
      in?" into "Waterproof Hiking Shoe colours available" using the
      conversation history — which the planner does not have. Sending only the
      raw message meant the planner saw a sentence whose subject was a pronoun
      referring to nothing, and it did the reasonable thing: it called no tool
      and the agent said it did not know. The rewrite was being computed and then
      thrown away for every step except retrieval.
    * **The order reference.** Already extracted once, by a model asked to do
      only that. Two independent extractions of the same string are two chances
      to transpose a digit, and a transposed digit is a lookup against somebody
      else's order number.
    """
    parts = []

    if context := state.get("context"):
        parts.append(f"STORE CONTENT ALREADY RETRIEVED:\n{context}")

    if order_ref := state.get("entities", {}).get("order_ref"):
        parts.append(f"ORDER NUMBER THE SHOPPER GAVE: {order_ref}")

    message = state.get("message", "")
    resolved = state.get("search_query", "")
    if resolved and resolved.lower() != message.lower():
        parts.append(f"WHAT THEY ARE ASKING, with references to earlier turns resolved: {resolved}")

    parts.append(f"<untrusted_customer_message>\n{message}\n</untrusted_customer_message>")
    return "\n\n".join(parts)


__all__ = ["PROMPT_NAME", "plan"]
