"""The graph runtime.

There is no agent yet — that is milestone 1.11 — so these tests build a small
one. That is not a workaround: **it is the expandability claim under test.** If
a graph can be assembled here from shared nodes without ``neura-agent-core``
learning the agent's name, then agent #2 costs what `agent-runtime.md §7` says
it costs.

What is worth testing about a graph is not that it runs. It is that it cannot be
built unsafely, and that the paths nobody exercises by hand still behave: a
verifier that errors, a tool that loops, a shopper asking about a stranger's
order.
"""

from __future__ import annotations

import pytest

from neura_agent_core.audit import AuditEntry, AuditEvent, InMemoryAuditLog
from neura_agent_core.graph import (
    CONFIG_KEY,
    AgentGraph,
    GraphContractError,
    Runtime,
    initial_state,
    propose,
)
from neura_agent_core.graph.nodes.verify import Groundedness, verify
from neura_agent_core.policy import ConversationBudget, PolicyEngine
from neura_agent_core.tools import SessionIdentity, ToolContext, ToolRegistry, tool
from neura_domain import Capability

TENANT = "tn_graph"
CONVERSATION = "cnv_graph"


# ── A minimal agent, built the way a real one would be ───────────────────────


@tool(
    name="get_order_status",
    description="Look up one order.",
    requires=[Capability.ORDER_READ],
    scopes=["care:order:read"],
    pii_output=True,
    requires_ownership="order_ref",
)
async def get_order_status(order_ref: str, ctx: ToolContext) -> str:
    return f"Order {order_ref} shipped on 2026-07-01, tracking TRK123."


@tool(name="escalate_to_human", description="Hand to a person.")
async def escalate_to_human(reason: str, ctx: ToolContext) -> str:
    return "escalated"


class StubLLM:
    """Stands in for the guard model. AGENTS.md: unit tests stub the LLM."""

    def __init__(self, *, grounded: bool = True, explode: bool = False) -> None:
        self.grounded = grounded
        self.explode = explode
        self.calls = 0

    async def chat_structured(self, role, request, schema):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.explode:
            raise RuntimeError("the guard model is down")

        class Result:
            value = Groundedness(
                grounded=self.grounded,
                unsupported_claim="" if self.grounded else "the refund window",
            )

        return Result()


def runtime(
    *,
    identity: SessionIdentity | None = None,
    llm: StubLLM | None = None,
    max_tool_calls: int = 4,
) -> Runtime:
    ctx = ToolContext(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        capabilities=frozenset({Capability.ORDER_READ}),
        scopes=frozenset({"care:order:read"}),
        identity=identity or SessionIdentity(),
    )
    registry = ToolRegistry([get_order_status, escalate_to_human])
    return Runtime(
        ctx=ctx,
        registry=registry,
        policy=PolicyEngine(registry),
        budget=ConversationBudget(max_tool_calls=max_tool_calls),
        llm=llm,
        prompts={"verify": "You check whether a draft is supported by evidence."},
    )


def config(rt: Runtime, thread: str = CONVERSATION) -> dict:
    return {"configurable": {CONFIG_KEY: rt, "thread_id": thread}}


def build_agent() -> AgentGraph:
    """A three-node agent: propose a tool call, act, compose, verify, respond."""

    async def plan(state, cfg=None):  # type: ignore[no-untyped-def]
        return propose([{"name": "get_order_status", "arguments": {"order_ref": "1001"}}])

    async def compose(state, cfg=None):  # type: ignore[no-untyped-def]
        results = " ".join(i.as_model_message() for i in state.get("invocations", []))
        return {"draft": f"Here is what I found: {results}"}

    async def respond(state, cfg=None):  # type: ignore[no-untyped-def]
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


# ── The contract the builder enforces ────────────────────────────────────────


class TestGraphContract:
    """ADR-0004 says guard and verify are *structural*. That is only true if a
    graph cannot be compiled without them."""

    def test_respond_cannot_be_reached_without_verify(self) -> None:
        graph = (
            AgentGraph()
            .node("compose", _noop)
            .node("respond", _noop)
            .entry("compose")
            .edge("compose", "respond")
        )

        with pytest.raises(GraphContractError, match="without passing through `verify`"):
            graph.compile()

    def test_a_detour_around_verify_is_also_caught(self) -> None:
        """The dangerous version is not a direct edge anyone would spot in
        review — it is a path added later that happens to route around."""
        graph = (
            AgentGraph()
            .node("compose", _noop)
            .node("shortcut", _noop)
            .node("respond", _noop)
            .entry("compose")
            .edge("compose", "shortcut")
            .edge("shortcut", "respond")
            .edge("compose", "verify")
            .edge("verify", "respond")
        )

        with pytest.raises(GraphContractError):
            graph.compile()

    def test_a_graph_without_escalate_is_refused(self) -> None:
        graph = AgentGraph().node("respond", _noop).entry("respond")
        del graph._nodes["escalate"]  # simulate an agent removing it

        with pytest.raises(GraphContractError, match="must have an `escalate` node"):
            graph.compile()

    def test_a_correct_graph_compiles(self) -> None:
        assert build_agent().compile() is not None

    def test_shared_nodes_are_present_without_being_asked_for(self) -> None:
        """So "we forgot to add verify" cannot happen by omission."""
        graph = AgentGraph()
        assert {"retrieve", "act", "verify", "escalate"} <= set(graph._nodes)


# ── Running a turn ───────────────────────────────────────────────────────────


class TestTurns:
    async def test_a_verified_answer_is_returned(self) -> None:
        rt = runtime(
            identity=SessionIdentity(verified_order_refs=frozenset({"1001"})),
            llm=StubLLM(grounded=True),
        )
        agent = build_agent().compile()

        final = await agent.ainvoke(
            initial_state(tenant_id=TENANT, conversation_id=CONVERSATION, message="where is 1001?"),
            config(rt),
        )

        assert final["reply"]
        assert "TRK123" in final["reply"]
        assert final["grounded"] is True
        assert not final.get("escalated")

    async def test_an_unverified_draft_escalates_and_is_not_sent(self) -> None:
        """The whole reason `verify` exists. A confident wrong answer about
        someone's money is the worst thing this product can do."""
        rt = runtime(
            identity=SessionIdentity(verified_order_refs=frozenset({"1001"})),
            llm=StubLLM(grounded=False),
        )
        final = (
            await build_agent()
            .compile()
            .ainvoke(
                initial_state(
                    tenant_id=TENANT, conversation_id=CONVERSATION, message="where is 1001?"
                ),
                config(rt),
            )
        )

        assert final["escalated"] is True
        assert final["grounded"] is False
        # The draft is carried to the human, explicitly unsent.
        assert "NOT SENT" in final["handoff"]
        assert "TRK123" in final["handoff"]
        assert final["reply"] != final["draft"]

    async def test_a_broken_verifier_fails_closed(self) -> None:
        """A verification step that lets answers through when it breaks is worse
        than none, because it looks like protection."""
        rt = runtime(
            identity=SessionIdentity(verified_order_refs=frozenset({"1001"})),
            llm=StubLLM(explode=True),
        )
        final = (
            await build_agent()
            .compile()
            .ainvoke(
                initial_state(
                    tenant_id=TENANT, conversation_id=CONVERSATION, message="where is 1001?"
                ),
                config(rt),
            )
        )

        assert final["escalated"] is True
        assert "could not be completed" in final["verify_reason"]

    async def test_an_unverified_shopper_never_reaches_the_tool(self) -> None:
        """Ownership is enforced by the engine, before the store is called."""
        rt = runtime(identity=SessionIdentity(), llm=StubLLM())
        final = (
            await build_agent()
            .compile()
            .ainvoke(
                initial_state(
                    tenant_id=TENANT, conversation_id=CONVERSATION, message="where is 1001?"
                ),
                config(rt),
            )
        )

        assert final["escalated"] is True
        assert "ownership" in final["escalation_reason"]
        # No tool ran, so nothing about a stranger's order entered the state.
        assert all(not i.ok for i in final["invocations"])
        assert "TRK123" not in str(final.get("handoff", ""))

    async def test_the_refusal_is_recorded_as_evidence(self) -> None:
        """The injection suite asserts on decisions, not on text — a reply can
        apologise politely while the tool ran anyway."""
        rt = runtime(identity=SessionIdentity(), llm=StubLLM())
        final = (
            await build_agent()
            .compile()
            .ainvoke(
                initial_state(
                    tenant_id=TENANT, conversation_id=CONVERSATION, message="where is 1001?"
                ),
                config(rt),
            )
        )

        decisions = final["decisions"]
        assert decisions
        assert all(not d.allowed for d in decisions)

    async def test_the_tool_cap_stops_a_loop(self) -> None:
        """Small models loop. The cap turns an infinite loop into an escalation,
        which is a good outcome rather than a hung request."""

        async def plan_many(state, cfg=None):  # type: ignore[no-untyped-def]
            return propose([{"name": "get_order_status", "arguments": {"order_ref": "1001"}}] * 10)

        rt = runtime(
            identity=SessionIdentity(verified_order_refs=frozenset({"1001"})),
            llm=StubLLM(),
            max_tool_calls=2,
        )
        agent = build_agent().node("plan", plan_many).compile()

        final = await agent.ainvoke(
            initial_state(tenant_id=TENANT, conversation_id=CONVERSATION, message="where is 1001?"),
            config(rt),
        )

        executed = [i for i in final["invocations"] if i.ok]
        assert len(executed) == 2

    async def test_the_runtime_must_be_supplied(self) -> None:
        """A graph invoked without its dependencies must fail loudly, not run
        with an empty tool set and answer from nothing."""
        with pytest.raises(Exception, match="without a Runtime"):
            await (
                build_agent()
                .compile()
                .ainvoke(
                    initial_state(tenant_id=TENANT, conversation_id=CONVERSATION, message="hello"),
                    {"configurable": {"thread_id": "x"}},
                )
            )


class TestVerifyDirectly:
    async def test_a_long_claim_with_no_evidence_is_refused(self) -> None:
        """The hallucination case: confident prose supported by nothing."""
        state = initial_state(tenant_id=TENANT, conversation_id=CONVERSATION, message="hi")
        state["draft"] = "Your refund was processed. " * 40

        result = await verify(state, config(runtime(llm=StubLLM())))

        assert result["grounded"] is False

    async def test_a_short_reply_with_no_evidence_is_fine(self) -> None:
        """A clarifying question asserts nothing and cannot be ungrounded.
        Requiring evidence for it would escalate every "what's your order
        number?"."""
        state = initial_state(tenant_id=TENANT, conversation_id=CONVERSATION, message="hi")
        state["draft"] = "Sure — could you tell me your order number?"

        result = await verify(state, config(runtime(llm=StubLLM())))

        assert result["grounded"] is True

    async def test_a_failed_tool_is_not_evidence(self) -> None:
        """ "The store did not answer" supports no claim about an order."""
        from neura_agent_core.tools import ToolInvocation

        state = initial_state(tenant_id=TENANT, conversation_id=CONVERSATION, message="hi")
        state["draft"] = "Your order shipped yesterday. " * 20
        state["invocations"] = [
            ToolInvocation(tool_name="get_order_status", ok=False, error="store unreachable")
        ]

        result = await verify(state, config(runtime(llm=StubLLM())))

        assert result["grounded"] is False


# ── The audit log ────────────────────────────────────────────────────────────


class TestAuditChain:
    async def test_entries_chain(self) -> None:
        log = InMemoryAuditLog()
        first = await log.record(_entry("allow"))
        second = await log.record(_entry("reject"))

        assert first != second
        assert len(log.for_tenant(TENANT)) == 2

    def test_the_same_content_at_a_different_position_hashes_differently(self) -> None:
        """Otherwise entries could be reordered without detection."""
        entry = _entry("allow")
        at_one = entry.digest(sequence=1, previous_hash="0" * 64, recorded_at=_NOW)
        at_two = entry.digest(sequence=2, previous_hash="0" * 64, recorded_at=_NOW)

        assert at_one != at_two

    def test_altering_the_payload_changes_the_hash(self) -> None:
        original = _entry("allow").digest(sequence=1, previous_hash="0" * 64, recorded_at=_NOW)
        tampered = AuditEntry(
            tenant_id=TENANT,
            event_type=AuditEvent.TOOL_DECISION,
            actor="policy",
            outcome="allow",
            payload={"tool": "something_else"},
        ).digest(sequence=1, previous_hash="0" * 64, recorded_at=_NOW)

        assert original != tampered

    def test_the_digest_is_stable_across_key_order(self) -> None:
        """Without sorted keys the same entry hashes differently between
        processes and verification fails for no reason."""
        a = AuditEntry(
            tenant_id=TENANT,
            event_type=AuditEvent.TOOL_DECISION,
            actor="policy",
            outcome="allow",
            payload={"b": 2, "a": 1},
        )
        b = AuditEntry(
            tenant_id=TENANT,
            event_type=AuditEvent.TOOL_DECISION,
            actor="policy",
            outcome="allow",
            payload={"a": 1, "b": 2},
        )

        assert a.digest(sequence=1, previous_hash="x", recorded_at=_NOW) == b.digest(
            sequence=1, previous_hash="x", recorded_at=_NOW
        )


from datetime import UTC, datetime  # noqa: E402

_NOW = datetime(2026, 7, 28, tzinfo=UTC)


def _entry(outcome: str) -> AuditEntry:
    return AuditEntry(
        tenant_id=TENANT,
        event_type=AuditEvent.TOOL_DECISION,
        actor="policy",
        outcome=outcome,
        conversation_id=CONVERSATION,
        payload={"tool": "get_order_status"},
    )


async def _noop(state, cfg=None):  # type: ignore[no-untyped-def]
    return {}
