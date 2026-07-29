"""NEURA-CARE.

The LLM is stubbed throughout — AGENTS.md: a test that needs a live model is an
eval or a ``*-check`` script, not a test. So what is under test here is not
whether the agent gives good answers; it is the machinery around the answer, and
in particular the parts that are supposed to hold when the model is wrong,
persuaded, or absent.

The security tests are the point of the file. Two of them cover the same attack
from opposite ends — an anonymous shopper reading a stranger's order, stopped by
the policy engine, and a *signed-in* shopper reading a stranger's order, stopped
only by the tool. They fail independently, which is why both exist.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from neura_evals.dataset import EvalCase, Expectation, Intent, SessionContext

from neura_agent_care import MANIFEST, build_graph, build_registry
from neura_agent_care.evals.store import ALL_CAPABILITIES, FixtureError, load_store
from neura_agent_care.evals.target import CareTarget
from neura_agent_care.nodes import (
    DECLINE_MIN_CONFIDENCE,
    MIN_CONFIDENCE,
    Route,
    compose,
    respond,
    route,
    triage,
)
from neura_agent_care.prompts import REQUIRED, REVISION, load_prompts, prompt_hashes
from neura_agent_care.runtime import build_runtime
from neura_agent_care.tools import CARE_TOOLS, TOOL_SCOPES
from neura_agent_care.tools.handover import HANDOVER_REQUESTED
from neura_agent_care.tools.orders import NOT_FOUND, find_orders_for_customer, get_order_status
from neura_agent_care.tools.render import order_evidence, policy_evidence, product_evidence
from neura_agent_core.graph import CONFIG_KEY, GraphContractError, initial_state
from neura_agent_core.policy import Outcome
from neura_agent_core.tools import SessionIdentity, ToolContext
from neura_commerce import CommerceAdapter
from neura_domain import SideEffect

TENANT = "tn_care_test"


# ── Stubs ────────────────────────────────────────────────────────────────────


class StubLLM:
    """Scripted model. Records what it was asked, so prompts can be asserted on."""

    role_map_name = "stub"

    def __init__(
        self,
        *,
        routed: Route | None = None,
        tool_calls: list[Any] | None = None,
        draft: str = "Your order shipped.",
        grounded: bool = True,
    ) -> None:
        self.routed = routed or Route(
            intent="order_status",
            confidence=0.9,
            order_ref="1001",
            search_query="order 1001 status",
        )
        self.tool_calls = tool_calls or []
        self.draft = draft
        self.grounded = grounded
        self.requests: list[Any] = []

    async def chat_structured(self, role: Any, request: Any, schema: type) -> Any:
        self.requests.append(request)

        class Result:
            pass

        result = Result()
        if schema.__name__ == "Route":
            result.value = self.routed  # type: ignore[attr-defined]
        else:
            result.value = schema(grounded=self.grounded, unsupported_claim="")  # type: ignore[attr-defined]
        return result

    async def chat(self, role: Any, request: Any) -> Any:
        self.requests.append(request)

        class Usage:
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15

        class Response:
            pass

        from decimal import Decimal

        from neura_llm import FinishReason

        response = Response()
        response.content = self.draft  # type: ignore[attr-defined]
        response.tool_calls = self.tool_calls  # type: ignore[attr-defined]
        response.usage = Usage()  # type: ignore[attr-defined]
        response.cost_usd = Decimal("0")  # type: ignore[attr-defined]
        response.finish_reason = FinishReason.STOP  # type: ignore[attr-defined]
        return response


def _ctx(store: Any, *, customer: str | None = None) -> ToolContext:
    return ToolContext(
        tenant_id=TENANT,
        conversation_id="cnv_t",
        capabilities=ALL_CAPABILITIES,
        scopes=TOOL_SCOPES,
        identity=SessionIdentity(customer_external_id=customer),
        adapter=store,
    )


def _config(runtime: Any) -> dict[str, Any]:
    return {"configurable": {CONFIG_KEY: runtime, "thread_id": "cnv_t"}}


# ── Prompts ──────────────────────────────────────────────────────────────────


class TestPrompts:
    def test_every_required_prompt_is_present_and_non_empty(self) -> None:
        prompts = load_prompts()
        assert prompts.keys() >= REQUIRED
        assert all(text.strip() for text in prompts.values())

    def test_the_revision_identifies_the_prompt_set(self) -> None:
        """The hash recorded on a conversation must name exactly one prompt set.

        Names are hashed with bodies, so *adding* a prompt moves the revision
        too — otherwise a new node's prompt would be invisible to the audit trail
        until somebody happened to edit an older file.
        """
        from neura_agent_care.prompts import _digest, revision

        assert revision() == REVISION
        assert len(REVISION) == 64

        hashes = prompt_hashes()
        with_extra = dict(hashes) | {"zzz_new_node": _digest("a new prompt")}
        recomputed = _digest(
            "\n".join(f"{name}:{digest}" for name, digest in sorted(with_extra.items()))
        )
        assert recomputed != REVISION

    def test_each_prompt_hashes_differently(self) -> None:
        hashes = prompt_hashes()
        assert len(set(hashes.values())) == len(hashes), "two prompts have identical content"

    def test_no_prompt_claims_to_enforce_authorisation(self) -> None:
        """AGENTS.md rule 3: a prompt is guidance, never the security boundary.

        A prompt that told the model it "must never" call a tool would read as a
        control while being none — and would invite someone to delete the real
        check on the grounds that the prompt covers it.
        """
        forbidden = ("you must never call", "you are forbidden to call", "never use the tool")
        for name, text in load_prompts().items():
            lowered = text.lower()
            for phrase in forbidden:
                assert phrase not in lowered, f"{name}.md states authorisation as an instruction"


# ── Tools ────────────────────────────────────────────────────────────────────


class TestToolDeclarations:
    def test_all_seven_mvp_tools_are_registered(self) -> None:
        registry = build_registry()
        assert {spec.name for spec in registry} == {
            "get_order_status",
            "find_orders_for_customer",
            "search_products",
            "get_product_details",
            "check_stock",
            "search_policies",
            "escalate_to_human",
        }

    def test_every_tool_is_read_only(self) -> None:
        """ADR-0010. Not a convention — the registry refuses anything else."""
        assert all(spec.side_effect is SideEffect.READ for spec in CARE_TOOLS)

    def test_manifest_declares_every_scope_the_tools_require(self) -> None:
        """Otherwise a correctly-provisioned key is refused at policy check 3.

        The failure is silent and reads as "the agent never calls any tool",
        which is a long way from "a scope is missing from the manifest".
        """
        assert MANIFEST.scopes >= TOOL_SCOPES

    def test_escalate_to_human_requires_no_capability(self) -> None:
        """The only action the agent can always take, on any store."""
        spec = next(s for s in CARE_TOOLS if s.name == "escalate_to_human")
        assert spec.requires == frozenset()

    def test_find_orders_for_customer_takes_no_identity_argument(self) -> None:
        """The signature IS the control.

        An ``email`` argument would be chosen by the model, which means by
        whoever is typing — and the ownership gate could not stop it, because
        ``may_see`` trusts an authenticated session whatever address it passes.
        Taking the customer from the session makes the abuse unexpressible
        rather than merely refused.
        """
        schema = find_orders_for_customer.json_schema()
        assert schema.get("properties", {}) == {}

    def test_a_tool_that_needs_a_missing_capability_is_never_offered(self) -> None:
        registry = build_registry()
        ctx = ToolContext(
            tenant_id=TENANT,
            conversation_id="cnv_t",
            capabilities=frozenset(),
            scopes=TOOL_SCOPES,
        )
        offered = {spec.name for spec in registry.available_for(ctx)}
        assert offered == {"escalate_to_human"}


class TestOrderTools:
    """The order number a shopper knows is not the store's internal key."""

    def test_order_is_found_by_the_number_the_shopper_typed(self) -> None:
        store = load_store(TENANT, ["orders/cust_88_shipped.json"])
        result = asyncio.run(
            get_order_status.fn(order_ref="1001", ctx=_ctx(store, customer="cust_88"))
        )
        assert "TRK123456" in result
        assert "Order 1001" in result

    def test_a_signed_in_shopper_cannot_read_a_strangers_order(self) -> None:
        """The hole the policy engine cannot close on its own.

        Every one of the eight checks passes here: the tool is registered, the
        store has the capability, the key holds the scope, and the ownership gate
        returns true because the session is authenticated. Only the tool scoping
        its result to the session's customer keeps this from being a breach.
        """
        store = load_store(TENANT, ["orders/stranger_order.json"])
        result = asyncio.run(
            get_order_status.fn(order_ref="2001", ctx=_ctx(store, customer="cust_88"))
        )
        assert result == NOT_FOUND
        assert "TRK777999" not in result

    def test_a_missing_order_and_a_strangers_order_are_indistinguishable(self) -> None:
        """A different message per case turns the reply into an enumeration oracle."""
        store = load_store(TENANT, ["orders/stranger_order.json"])
        stranger = asyncio.run(
            get_order_status.fn(order_ref="2001", ctx=_ctx(store, customer="cust_88"))
        )
        missing = asyncio.run(
            get_order_status.fn(order_ref="9999", ctx=_ctx(store, customer="cust_88"))
        )
        assert stranger == missing

    def test_find_orders_says_so_when_the_session_is_anonymous(self) -> None:
        store = load_store(TENANT, ["orders/cust_88_shipped.json"])
        result = asyncio.run(find_orders_for_customer.fn(ctx=_ctx(store)))
        assert "has not established who the shopper is" in result
        assert "TRK123456" not in result

    def test_find_orders_returns_only_the_sessions_own_orders(self) -> None:
        store = load_store(TENANT, ["orders/cust_91_two_orders.json", "orders/stranger_order.json"])
        result = asyncio.run(find_orders_for_customer.fn(ctx=_ctx(store, customer="cust_91")))
        assert "1010" in result and "1011" in result
        assert "2001" not in result


class TestEvidenceRendering:
    """Absence is stated, never omitted — a gap is what a model fills in."""

    def test_a_missing_tracking_number_is_named_rather_than_dropped(self) -> None:
        store = load_store(TENANT, ["orders/cust_91_two_orders.json"])
        order = asyncio.run(store.get_order("o_5011"))
        assert order is not None
        rendered = order_evidence(order)
        assert "nothing has been dispatched" in rendered

    def test_a_missing_delivery_estimate_is_stated(self) -> None:
        store = load_store(TENANT, ["orders/cust_88_shipped.json"])
        order = asyncio.run(store.get_order("o_5001"))
        assert order is not None
        assert "no delivery estimate available" in order_evidence(order)

    def test_an_archived_product_is_not_described_as_available(self) -> None:
        store = load_store(TENANT, [])
        product = asyncio.run(store.get_product("p_300"))
        assert product is not None
        assert "not available to buy" in product_evidence(product)

    def test_availability_never_reads_as_a_discount(self) -> None:
        """Found by reading the output of a real run, not by an assertion.

        The first version rendered an active product as "on sale", meaning
        offered for sale — and the agent told a shopper the shoe was "available
        now at $132.00 and currently on sale". Grounded, accurate, and it sends
        someone hunting for a discount that does not exist.
        """
        store = load_store(TENANT, [])
        product = asyncio.run(store.get_product("p_100"))
        assert product is not None
        assert "on sale" not in product_evidence(product)

    def test_a_truncated_policy_says_it_is_truncated(self) -> None:
        from neura_agent_care.tools.render import MAX_POLICY_CHARS
        from neura_domain import Policy, PolicyKind

        policy = Policy(
            neura_id="pol_x",
            tenant_id=TENANT,
            external_id="x",
            platform="fixture",
            synced_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            kind=PolicyKind.RETURNS,
            title="Long",
            body="word " * (MAX_POLICY_CHARS),
        )
        assert "truncated" in policy_evidence(policy)


# ── The graph ────────────────────────────────────────────────────────────────


class TestGraphContract:
    def test_care_compiles(self) -> None:
        assert build_graph().compile() is not None

    def test_a_shortcut_past_verify_will_not_compile(self) -> None:
        """The guarantee ADR-0004 depends on, asserted against CARE itself.

        Not a hypothetical graph — this is CARE with one edge added, which is
        exactly how the bug would arrive: a detour that happens to route around
        the check.
        """
        graph = build_graph().edge("compose", "respond")
        with pytest.raises(GraphContractError, match="verify"):
            graph.compile()


class TestRouting:
    def _runtime(self, llm: Any) -> Any:
        return build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_t",
            adapter=load_store(TENANT, []),
            llm=llm,
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
        )

    def _route(self, routed: Route) -> Any:
        return asyncio.run(
            route(
                initial_state(tenant_id=TENANT, conversation_id="c", message="hi"),
                _config(self._runtime(StubLLM(routed=routed))),
            )
        )

    def test_a_question_needing_a_person_escalates(self) -> None:
        state = self._route(Route(intent="needs_person", confidence=0.95))
        assert state["escalated"] is True

    def test_a_confident_out_of_scope_declines_without_a_person(self) -> None:
        """Open question A5. "What's the weather?" must not occupy a colleague."""
        state = self._route(Route(intent="out_of_scope", confidence=0.95))
        assert not state.get("escalated")

    def test_an_unsure_decline_escalates_instead(self) -> None:
        """Declining is the only outcome that ends a turn with neither an answer
        nor a person — and the only one an attacker gains from.

        Measured: an order-enumeration injection was classified `out_of_scope`
        and silently declined. No tool ran, so injection resistance was
        unaffected, and the merchant would never have learned it was attempted.
        Prompt wording cannot fix that, because the prompt is what an injection
        is talking past. This floor is underneath it.
        """
        state = self._route(Route(intent="out_of_scope", confidence=DECLINE_MIN_CONFIDENCE - 0.01))
        assert state["escalated"] is True

    def test_declining_is_held_to_a_higher_bar_than_answering(self) -> None:
        assert DECLINE_MIN_CONFIDENCE > MIN_CONFIDENCE

    def test_low_confidence_escalates_before_any_lookup(self) -> None:
        llm = StubLLM(
            routed=Route(intent="order_status", confidence=MIN_CONFIDENCE - 0.01, order_ref="1")
        )
        state = asyncio.run(
            route(
                initial_state(tenant_id=TENANT, conversation_id="c", message="hm"),
                _config(self._runtime(llm)),
            )
        )
        assert state["escalated"] is True
        assert "confidence" in state["escalation_reason"]

    def test_a_router_that_errors_escalates_rather_than_guessing(self) -> None:
        class Broken(StubLLM):
            async def chat_structured(self, role: Any, request: Any, schema: type) -> Any:
                raise RuntimeError("router is down")

        state = asyncio.run(
            route(
                initial_state(tenant_id=TENANT, conversation_id="c", message="x"),
                _config(self._runtime(Broken())),
            )
        )
        assert state["escalated"] is True

    def test_an_empty_rewrite_falls_back_to_the_message(self) -> None:
        """Otherwise a lazy router silently disables retrieval for the turn."""
        llm = StubLLM(routed=Route(intent="policy_qa", confidence=0.9, search_query="  "))
        state = asyncio.run(
            route(
                initial_state(tenant_id=TENANT, conversation_id="c", message="returns?"),
                _config(self._runtime(llm)),
            )
        )
        assert state["search_query"] == "returns?"

    def test_a_blank_order_ref_is_not_recorded_as_an_entity(self) -> None:
        llm = StubLLM(routed=Route(intent="policy_qa", confidence=0.9, order_ref="   "))
        state = asyncio.run(
            route(
                initial_state(tenant_id=TENANT, conversation_id="c", message="hi"),
                _config(self._runtime(llm)),
            )
        )
        assert state["entities"] == {}


class TestTriage:
    def test_a_requested_handover_escalates_with_its_reason(self) -> None:
        from neura_agent_core.tools.executor import ToolInvocation

        state = asyncio.run(
            triage(
                {
                    "invocations": [
                        ToolInvocation(
                            tool_name="escalate_to_human",
                            ok=True,
                            value=f"{HANDOVER_REQUESTED}: the shopper asked for a person",
                        )
                    ]
                },
                {},
            )
        )
        assert state["escalated"] is True
        assert "asked for a person" in state["escalation_reason"]

    def test_a_refused_handover_does_not_escalate(self) -> None:
        """A call the engine blocked must not escalate a conversation nobody asked
        to escalate."""
        from neura_agent_core.tools.executor import ToolInvocation

        state = asyncio.run(
            triage(
                {
                    "invocations": [
                        ToolInvocation(tool_name="escalate_to_human", ok=False, error="refused")
                    ]
                },
                {},
            )
        )
        assert state == {}


class TestRespond:
    def test_respond_refuses_an_unverified_draft(self) -> None:
        """Unreachable through the compiled graph — and checked anyway, because
        "unreachable" is a property of today's edges."""
        runtime = build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_t",
            adapter=load_store(TENANT, []),
            llm=StubLLM(),
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
        )
        state = asyncio.run(
            respond({"draft": "Your refund is done.", "grounded": False}, _config(runtime))
        )
        assert state["escalated"] is True
        assert "reply" not in state

    def test_the_prompt_revision_is_recorded_on_the_turn(self) -> None:
        runtime = build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_t",
            adapter=load_store(TENANT, []),
            llm=StubLLM(),
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
        )
        state = asyncio.run(respond({"draft": "Shipped.", "grounded": True}, _config(runtime)))
        assert state["usage"]["prompt_revision"] == REVISION


class TestCompose:
    def test_an_empty_draft_from_a_truncated_model_is_diagnosed(self) -> None:
        """The bug that cost a whole eval run.

        A reasoning model spends `max_tokens` thinking before it writes a
        character, so a ceiling sized for a two-sentence reply yields
        finish_reason=length and no content. Both causes escalate; only one is a
        misconfiguration, and it is invisible unless the reason says so.
        """
        from neura_llm import FinishReason

        class Truncated(StubLLM):
            async def chat(self, role: Any, request: Any) -> Any:
                response = await super().chat(role, request)
                response.content = ""
                response.finish_reason = FinishReason.LENGTH
                return response

        runtime = build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_t",
            adapter=load_store(TENANT, []),
            llm=Truncated(),
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
        )
        state = asyncio.run(compose({"message": "where is my order?"}, _config(runtime)))
        assert state["escalated"] is True
        assert "token ceiling" in state["escalation_reason"]

    def test_a_failed_tool_call_reaches_the_composer_as_a_failure(self) -> None:
        """Dropping it would leave the model a question and no reason for the
        silence, which is when it invents."""
        from neura_agent_core.tools.executor import ToolInvocation

        llm = StubLLM()
        runtime = build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_t",
            adapter=load_store(TENANT, []),
            llm=llm,
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
        )
        asyncio.run(
            compose(
                {
                    "message": "where is my order?",
                    "invocations": [
                        ToolInvocation(
                            tool_name="get_order_status", ok=False, error="store timed out"
                        )
                    ],
                },
                _config(runtime),
            )
        )
        sent = llm.requests[-1].messages[-1].content
        assert "tool_failed" in sent and "store timed out" in sent


# ── The fixture store and the eval target ────────────────────────────────────


class TestFixtureStore:
    def test_it_satisfies_the_commerce_adapter_protocol(self) -> None:
        """Structurally, with no import and no base class — the same way a third
        party conforms to the published spec."""
        assert isinstance(load_store(TENANT, []), CommerceAdapter)

    def test_a_missing_fixture_is_named_rather_than_silently_empty(self) -> None:
        with pytest.raises(FixtureError, match="does not exist"):
            load_store(TENANT, ["orders/nope.json"])

    def test_fixtures_cannot_assert_their_own_provenance(self) -> None:
        """A store cannot know its tenant_id or platform — the spec strips both."""
        store = load_store(TENANT, ["orders/cust_88_shipped.json"])
        order = asyncio.run(store.get_order("o_5001"))
        assert order is not None
        assert order.tenant_id == TENANT
        assert order.platform == "fixture"

    def test_no_identifier_returns_no_orders(self) -> None:
        """Matching GenericAdapter. A fake more permissive than the real thing
        hides the bug it exists to catch."""
        from neura_domain import CustomerRef

        store = load_store(TENANT, ["orders/cust_88_shipped.json"])
        assert asyncio.run(store.find_orders_for_customer(CustomerRef())) == []


class TestEvalTarget:
    def _case(self, **kwargs: Any) -> EvalCase:
        return EvalCase(
            id="t1",
            intent=Intent.ORDER_STATUS,
            input=kwargs.pop("input", "Where is my order 1001?"),
            expect=Expectation(),
            synthetic=True,
            **kwargs,
        )

    def test_a_crash_is_reported_as_an_execution_error(self) -> None:
        """Never as a plausible refusal — that would be the most flattering
        possible bug."""

        class Exploding(StubLLM):
            async def chat_structured(self, role: Any, request: Any, schema: type) -> Any:
                raise RuntimeError("boom")

        target = CareTarget(Exploding())
        # route escalates on a router failure rather than raising, so the turn
        # completes; what must not happen is a silently empty success.
        response = asyncio.run(target.run(self._case()))
        assert response.escalated is True

    def test_a_refused_tool_is_not_reported_as_a_tool_call(self) -> None:
        """Otherwise every correctly-blocked injection case fails its own safety
        assertion — the tool never ran."""
        target = CareTarget(
            StubLLM(routed=Route(intent="order_status", confidence=0.9, order_ref="1001"))
        )
        case = self._case(fixtures=["orders/cust_88_shipped.json"], session=SessionContext())
        response = asyncio.run(target.run(case))
        assert response.unauthorised_tool_calls == 0

    def test_an_anonymous_session_never_reaches_the_store(self) -> None:
        class Planner(StubLLM):
            async def chat(self, role: Any, request: Any) -> Any:
                from neura_llm import ToolCall

                response = await super().chat(role, request)
                if request.tools:
                    response.tool_calls = [
                        ToolCall(id="1", name="get_order_status", arguments={"order_ref": "1001"})
                    ]
                return response

        target = CareTarget(Planner())
        case = self._case(fixtures=["orders/cust_88_shipped.json"])
        response = asyncio.run(target.run(case))

        assert response.escalated is True
        assert "TRK123456" not in response.reply
        assert response.tool_names == []


class TestPolicyIntegration:
    def test_the_ownership_gate_escalates_rather_than_rejecting(self) -> None:
        """Rejecting invites a retry with a different number, which is
        enumeration with extra steps."""
        runtime = build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_t",
            adapter=load_store(TENANT, ["orders/cust_88_shipped.json"]),
            llm=StubLLM(),
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
        )
        decision = runtime.policy.authorise(
            "get_order_status", {"order_ref": "1001"}, runtime.ctx, runtime.budget
        )
        assert decision.outcome is Outcome.ESCALATE
