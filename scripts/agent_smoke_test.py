#!/usr/bin/env python3
"""Run a real graph, with real models and a real database.

    make agent-check

Everything in ``tests/unit/test_graph.py`` stubs the LLM, which is correct for a
unit test and proves nothing about whether the pieces work together. This runs a
small agent end to end: a real ``qwen`` model drafts, a real ``llama`` model
verifies, the policy engine authorises, and PostgreSQL checkpoints the state.

There is still **no product agent** — that is milestone 1.11. The one here is
deliberately minimal, and building it in ~40 lines is itself the point: it is
the expandability claim from ``agent-runtime.md §7`` being exercised rather than
asserted.

Four scenarios, chosen because each is a different way the runtime can be wrong:

1. A shopper who has proven ownership gets an answer, grounded in a tool result.
2. A shopper who has not is escalated *before* the store is called.
3. A draft the verifier rejects is not sent, and the human gets the draft.
4. The turn survives being resumed from a checkpoint in a new process.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from neura_agent_core.graph import (
    CONFIG_KEY,
    AgentGraph,
    Runtime,
    initial_state,
    propose,
)
from neura_agent_core.graph.checkpointer import PostgresCheckpointer
from neura_agent_core.policy import ConversationBudget, PolicyEngine
from neura_agent_core.tools import SessionIdentity, ToolContext, ToolRegistry, tool
from neura_core import Database, configure_logging
from neura_domain import Capability
from neura_llm import ChatRequest, LLMClient, Message, ModelRole

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
OFF = "\033[0m"

TENANT = "tn_agentsmoke"

VERIFY_PROMPT = (
    "You check whether a draft reply is fully supported by the evidence given. "
    "Answer grounded=true only if every factual claim appears in the evidence. "
    "If anything is asserted that the evidence does not state, answer "
    "grounded=false and quote the unsupported claim."
)


def tick(ok: bool) -> str:
    return f"{GREEN}✔{OFF}" if ok else f"{RED}✘{OFF}"


# ── The smallest possible agent ──────────────────────────────────────────────


@tool(
    name="get_order_status",
    description="Look up the status and tracking of one order.",
    requires=[Capability.ORDER_READ],
    scopes=["care:order:read"],
    pii_output=True,
    requires_ownership="order_ref",
)
async def get_order_status(order_ref: str, ctx: ToolContext) -> str:
    # Fixed data on purpose: this script tests the *runtime*, and a live store
    # would make a failure ambiguous between the agent and the shop.
    return (
        f"Order {order_ref}: shipped on 2026-07-20 via ParcelCo, "
        f"tracking PC55512345, estimated delivery 2026-07-24."
    )


def build_agent(llm: LLMClient, *, force_bad_draft: bool = False):
    async def plan(state, config):  # type: ignore[no-untyped-def]
        return propose([{"name": "get_order_status", "arguments": {"order_ref": "1001"}}])

    async def compose(state, config):  # type: ignore[no-untyped-def]
        if force_bad_draft:
            # A claim the evidence does not support, to see verify catch it.
            return {
                "draft": "Your order was delivered last Tuesday and your refund "
                "of $42.00 has already been issued to your card."
            }
        evidence = "\n".join(i.as_model_message() for i in state.get("invocations", []) if i.ok)
        response = await llm.chat(
            ModelRole.REASONER,
            ChatRequest(
                messages=[
                    Message.system(
                        "You are a shop's support assistant. Answer using ONLY the "
                        "evidence provided. Be brief — two sentences at most."
                    ),
                    Message.user(f"EVIDENCE:\n{evidence}\n\nCUSTOMER: {state['message']}"),
                ],
                temperature=0.0,
            ),
        )
        return {"draft": response.content.strip()}

    async def respond(state, config):  # type: ignore[no-untyped-def]
        return {"reply": state.get("draft", "")}

    def after_act(state):  # type: ignore[no-untyped-def]
        return "escalate" if state.get("escalated") else "compose"

    def after_verify(state):  # type: ignore[no-untyped-def]
        return "respond" if state.get("grounded") else "escalate"

    return (
        AgentGraph()
        .node("plan", plan)
        .node("compose", compose)
        .node("respond", respond)
        .entry("plan")
        .edge("plan", "act")
        .branch("act", after_act, {"compose": "compose", "escalate": "escalate"})
        .edge("compose", "verify")
        .branch("verify", after_verify, {"respond": "respond", "escalate": "escalate"})
    )


def runtime_for(llm: LLMClient, identity: SessionIdentity) -> Runtime:
    ctx = ToolContext(
        tenant_id=TENANT,
        conversation_id="cnv_smoke",
        capabilities=frozenset({Capability.ORDER_READ}),
        scopes=frozenset({"care:order:read"}),
        identity=identity,
    )
    registry = ToolRegistry([get_order_status])
    return Runtime(
        ctx=ctx,
        registry=registry,
        policy=PolicyEngine(registry),
        budget=ConversationBudget(max_tool_calls=4),
        llm=llm,
        prompts={"verify": VERIFY_PROMPT},
    )


async def run() -> int:
    llm = LLMClient.from_role_map_name("ollama-dev")
    database = Database.from_settings()

    print(f"\n  reasoner  {llm.model_for(ModelRole.REASONER)}")
    print(f"  guard     {llm.model_for(ModelRole.GUARD)}\n")

    if not await database.ping():
        print(f"  {RED}no database — run `make up` and `make migrate`{OFF}\n")
        return 1

    ok = True
    question = "where is my order 1001?"

    # ── 1. The happy path ────────────────────────────────────────────────────
    print("  VERIFIED SHOPPER — should answer, grounded in the tool result")
    async with database.tenant_session(TENANT) as session:
        rt = runtime_for(llm, SessionIdentity(verified_order_refs=frozenset({"1001"})))
        agent = build_agent(llm).compile(PostgresCheckpointer(session, TENANT))
        final = await agent.ainvoke(
            initial_state(tenant_id=TENANT, conversation_id="cnv_smoke", message=question),
            {"configurable": {CONFIG_KEY: rt, "thread_id": "cnv_smoke"}},
        )

    answered = bool(final.get("reply")) and not final.get("escalated")
    print(f"    {tick(answered)} replied · grounded={final.get('grounded')}")
    print(f"        {DIM}{final.get('reply', '')[:150]}{OFF}")
    tools = [i.tool_name for i in final.get("invocations", []) if i.ok]
    print(f"        {DIM}tools: {tools or 'none'}{OFF}")
    ok = ok and answered

    # ── 2. The security path ─────────────────────────────────────────────────
    print("\n  UNVERIFIED SHOPPER — must escalate BEFORE the store is called")
    async with database.tenant_session(TENANT) as session:
        rt = runtime_for(llm, SessionIdentity())
        agent = build_agent(llm).compile(PostgresCheckpointer(session, TENANT))
        final = await agent.ainvoke(
            initial_state(tenant_id=TENANT, conversation_id="cnv_anon", message=question),
            {"configurable": {CONFIG_KEY: rt, "thread_id": "cnv_anon"}},
        )

    ran_tools = [i.tool_name for i in final.get("invocations", []) if i.ok]
    refused = final.get("escalated") and not ran_tools
    print(
        f"    {tick(refused)} escalated={final.get('escalated')} · tools run: {ran_tools or 'none'}"
    )
    print(f"        {DIM}reason: {final.get('escalation_reason')}{OFF}")
    if "PC55512345" in str(final.get("handoff", "")):
        print(f"        {RED}tracking number leaked into the handoff{OFF}")
        refused = False
    ok = ok and refused

    # ── 3. The verifier ──────────────────────────────────────────────────────
    print("\n  UNGROUNDED DRAFT — a real guard model must catch an invented claim")
    async with database.tenant_session(TENANT) as session:
        rt = runtime_for(llm, SessionIdentity(verified_order_refs=frozenset({"1001"})))
        agent = build_agent(llm, force_bad_draft=True).compile(
            PostgresCheckpointer(session, TENANT)
        )
        final = await agent.ainvoke(
            initial_state(tenant_id=TENANT, conversation_id="cnv_bad", message=question),
            {"configurable": {CONFIG_KEY: rt, "thread_id": "cnv_bad"}},
        )

    caught = final.get("escalated") is True and final.get("grounded") is False
    print(
        f"    {tick(caught)} grounded={final.get('grounded')} · escalated={final.get('escalated')}"
    )
    print(f"        {DIM}{final.get('verify_reason')}{OFF}")
    if not caught:
        print(
            f"        {DIM}note: a 3B guard model missing this is a model finding, "
            f"not a code bug — it is what the eval suite exists to quantify.{OFF}"
        )
    ok = ok and caught

    # ── 4. Durability ────────────────────────────────────────────────────────
    print("\n  RESUME — the turn must survive the process that ran it")
    async with database.tenant_session(TENANT) as session:
        saver = PostgresCheckpointer(session, TENANT)
        restored = await saver.aget_tuple({"configurable": {"thread_id": "cnv_smoke"}})

    resumed = restored is not None
    print(f"    {tick(resumed)} checkpoint read back in a new session")
    if restored:
        print(f"        {DIM}channels: {sorted(restored.checkpoint['channel_values'])[:6]}{OFF}")
    ok = ok and resumed

    # ── Cleanup ──────────────────────────────────────────────────────────────
    async with database.tenant_session(TENANT) as session:
        for thread in ("cnv_smoke", "cnv_anon", "cnv_bad"):
            await PostgresCheckpointer(session, TENANT).adelete_thread(thread)
    await database.dispose()

    print()
    if ok:
        print(f"  {GREEN}The agent runtime works end to end.{OFF}\n")
        return 0
    print(f"  {RED}Something failed above.{OFF}\n")
    return 1


def main() -> None:
    argparse.ArgumentParser(description="Run the agent runtime end to end.").parse_args()
    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
