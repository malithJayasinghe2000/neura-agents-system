"""The ``plan`` node — choosing which lookups to run.

The model proposes tool calls here; ``act`` authorises and executes them.
Keeping the two apart is the point of the split: proposing is a language task
the model is good at, authorising is a security decision it must have no part
in. Nothing this node returns is trusted — every proposal goes through all eight
policy checks before anything touches a store.

**Only the tools this conversation may actually use are offered.** The registry
filters by the store's declared capabilities before the definitions are built,
so a store with no live inventory feed produces a model that has never heard of
``check_stock``. That is stronger than refusing the call afterwards: you cannot
talk a model into invoking a tool it was never shown.

**Unlike CARE, proposing nothing is almost never right here.** CARE can answer a
policy question from indexed text with no lookup at all. SELL cannot: a
recommendation names products, `shortlist` only admits products the catalogue
actually returned, and a turn with no successful catalogue lookup escalates
rather than guessing. So the prompt asks for a search on every answerable turn,
and a plan with no tools is left to fail honestly at `shortlist` rather than
being forced here — a node that manufactured a tool call to satisfy a later
check would be defeating the check.
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
    """Ask the reasoner which lookups would answer this."""
    runtime = runtime_of(config or {})

    available = runtime.registry.available_for(runtime.ctx)
    if not available:
        # A real configuration, not a bug: a store declaring no capabilities
        # SELL can use. Said out loud rather than producing an empty plan that
        # looks like the model deciding it needed nothing.
        log.info("sell_plan_no_tools", conversation_id=state.get("conversation_id"))
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
        log.warning(
            "sell_plan_failed", conversation_id=state.get("conversation_id"), error=str(exc)
        )
        return {
            "escalated": True,
            "escalation_reason": f"tool planning failed: {type(exc).__name__}",
            # A provider that is not there is not an agent decision. Recorded
            # separately so the eval skips this case instead of scoring it (E6).
            **infra_error(exc, "the reasoner was unreachable while planning"),
        }

    proposals = [{"name": call.name, "arguments": call.arguments} for call in response.tool_calls]

    log.info(
        "sell_planned",
        conversation_id=state.get("conversation_id"),
        proposed=[call.name for call in response.tool_calls],
        offered=[spec.name for spec in available],
    )
    return propose(proposals)


def _render(state: AgentState) -> str:
    """What the planner sees.

    Everything the router already worked out is passed on explicitly rather than
    left for this model to re-derive. CARE measured the cost of not doing this:
    the planner saw a sentence whose subject was a pronoun referring to nothing,
    called no tool, and the agent said it did not know — while the rewrite was
    being computed and thrown away for every step except retrieval.

    The constraints are passed as *context, not as instructions to filter on*.
    `shortlist` enforces the price ceiling in code; telling the planner about it
    only helps it search well.
    """
    parts = []

    if context := state.get("context"):
        parts.append(f"STORE CONTENT ALREADY RETRIEVED:\n{context}")

    entities = state.get("entities", {})
    if named := entities.get("named_products"):
        parts.append(f"PRODUCTS THE SHOPPER NAMED: {named.replace('|', ', ')}")
    if ceiling := entities.get("max_price"):
        parts.append(f"PRICE CEILING THEY STATED: {ceiling}")
    if attributes := entities.get("required_attributes"):
        parts.append(f"ATTRIBUTES THEY ASKED FOR: {attributes.replace('|', ', ')}")

    message = state.get("message", "")
    if (resolved := state.get("search_query", "")) and resolved.lower() != message.lower():
        parts.append(f"WHAT THEY ARE LOOKING FOR, with earlier turns resolved: {resolved}")

    parts.append(f"<untrusted_customer_message>\n{message}\n</untrusted_customer_message>")
    return "\n\n".join(parts)


__all__ = ["PROMPT_NAME", "plan"]
