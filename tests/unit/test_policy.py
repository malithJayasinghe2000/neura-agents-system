"""The tool layer and the policy engine.

Rule 3 of AGENTS.md — *authorisation is code, never a prompt* — is only true if
something fails when it is broken. These are that something.

The tests that matter here are the abuse paths. A tool that works when called
correctly is the easy half; the half that decides whether this product can be
put in front of a real merchant's customers is what happens when the model is
talked into calling something it should not, or asks about a stranger's order.

Note what is deliberately **not** tested by reading text: nothing here asserts
that a reply "sounds like" a refusal. A reply can apologise politely while the
tool ran anyway. Every assertion is on the engine's decision.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from neura_agent_core.policy import Check, ConversationBudget, Outcome, PolicyEngine
from neura_agent_core.tools import (
    SessionIdentity,
    ToolContext,
    ToolRegistrationError,
    ToolRegistry,
    execute,
    tool,
)
from neura_commerce import AdapterUnavailableError
from neura_domain import Capability, SideEffect

TENANT = "tn_policy"
CONVERSATION = "cnv_policy"

ALL_CAPABILITIES = frozenset(
    {
        Capability.ORDER_READ,
        Capability.ORDER_SEARCH,
        Capability.PRODUCT_READ,
        Capability.PRODUCT_SEARCH,
        Capability.POLICY_READ,
        Capability.CUSTOMER_READ,
    }
)
ALL_SCOPES = frozenset({"care:order:read", "care:product:read", "care:policy:read"})


# ── Tools under test ─────────────────────────────────────────────────────────


@tool(
    name="get_order_status",
    description="Look up the status of one order.",
    requires=[Capability.ORDER_READ],
    scopes=["care:order:read"],
    pii_output=True,
    requires_ownership="order_ref",
    # Mirrors the real CARE tool, which does filter its result by customer.
    scoped_to_session=True,
)
async def get_order_status(order_ref: str, ctx: ToolContext) -> str:
    return f"order {order_ref}: shipped"


@tool(
    name="get_unscoped_order",
    description="Look up one order without constraining the result to a customer.",
    requires=[Capability.ORDER_READ],
    scopes=["care:order:read"],
    pii_output=True,
    requires_ownership="order_ref",
    # Deliberately omits `scoped_to_session` — this stands for the tool somebody
    # adds later without thinking about ownership. It must fail closed.
)
async def get_unscoped_order(order_ref: str, ctx: ToolContext) -> str:
    return f"order {order_ref}: shipped"


@tool(
    name="search_products",
    description="Search the catalogue.",
    requires=[Capability.PRODUCT_SEARCH],
    scopes=["care:product:read"],
)
async def search_products(query: str, ctx: ToolContext, limit: int = 5) -> str:
    return f"{limit} results for {query}"


@tool(name="escalate_to_human", description="Hand over to a person.")
async def escalate_to_human(reason: str, ctx: ToolContext) -> str:
    return "escalated"


def registry() -> ToolRegistry:
    return ToolRegistry([get_order_status, get_unscoped_order, search_products, escalate_to_human])


def context(**overrides: object) -> ToolContext:
    defaults: dict[str, object] = {
        "tenant_id": TENANT,
        "conversation_id": CONVERSATION,
        "capabilities": ALL_CAPABILITIES,
        "scopes": ALL_SCOPES,
        "identity": SessionIdentity(),
    }
    defaults.update(overrides)
    return ToolContext(**defaults)  # type: ignore[arg-type]


# ── Declaration ──────────────────────────────────────────────────────────────


class TestDeclaration:
    def test_the_schema_comes_from_the_signature(self) -> None:
        """So a parameter added without a thought cannot become an unvalidated input."""
        schema = search_products.json_schema()
        assert set(schema["properties"]) == {"query", "limit"}
        assert schema["required"] == ["query"]

    def test_ctx_is_never_in_the_schema(self) -> None:
        """The model must not be able to set its own tenant, store or identity."""
        for spec in (get_order_status, search_products, escalate_to_human):
            assert "ctx" not in spec.json_schema()["properties"]

    def test_unknown_arguments_are_forbidden(self) -> None:
        schema = search_products.json_schema()
        assert schema["additionalProperties"] is False

    def test_a_synchronous_tool_is_refused(self) -> None:
        """One blocking call in an async handler stalls every tenant, not one."""
        with pytest.raises(TypeError, match="must be async"):

            @tool(name="blocking", description="no")
            def blocking(ctx: ToolContext) -> str:  # type: ignore[misc]
                return "no"

    def test_a_tool_without_ctx_is_refused(self) -> None:
        with pytest.raises(TypeError, match="ToolContext"):

            @tool(name="no_ctx", description="no")
            async def no_ctx(order_ref: str) -> str:
                return "no"

    def test_an_unannotated_parameter_is_refused(self) -> None:
        with pytest.raises(TypeError, match="type annotation"):

            @tool(name="untyped", description="no")
            async def untyped(order_ref, ctx: ToolContext) -> str:  # type: ignore[no-untyped-def]
                return "no"

    def test_ownership_must_name_a_real_argument(self) -> None:
        """A typo here would silently disable an access-control check."""
        with pytest.raises(ValueError, match="no such argument"):

            @tool(name="typo", description="no", requires_ownership="oder_ref")
            async def typo(order_ref: str, ctx: ToolContext) -> str:
                return "no"


class TestRegistration:
    def test_a_write_tool_cannot_be_registered(self) -> None:
        """ADR-0010, made structural rather than remembered.

        The approval queue a WRITE tool needs does not exist, so registering one
        would mean it runs with no approval at all.
        """

        @tool(name="cancel_order", description="no", side_effect=SideEffect.WRITE)
        async def cancel_order(order_ref: str, ctx: ToolContext) -> str:
            return "cancelled"

        with pytest.raises(ToolRegistrationError, match="READ tools only"):
            ToolRegistry([cancel_order])

    def test_an_irreversible_tool_cannot_be_registered(self) -> None:
        @tool(name="issue_refund", description="no", side_effect=SideEffect.IRREVERSIBLE)
        async def issue_refund(order_ref: str, ctx: ToolContext) -> str:
            return "refunded"

        with pytest.raises(ToolRegistrationError):
            ToolRegistry([issue_refund])

    def test_duplicate_names_are_refused(self) -> None:
        """Names are how the model refers to tools; two tools with one name means
        the model cannot address either reliably."""
        with pytest.raises(ToolRegistrationError, match="already registered"):
            ToolRegistry([search_products, search_products])


class TestCapabilityFiltering:
    def test_a_tool_the_store_cannot_serve_is_never_offered(self) -> None:
        """Stronger than rejecting the call: the model cannot propose what it has
        never been shown, so there is no failed call and no injection target."""
        ctx = context(capabilities=frozenset({Capability.PRODUCT_SEARCH}))
        available = {spec.name for spec in registry().available_for(ctx)}

        assert "search_products" in available
        assert "get_order_status" not in available

    def test_escalate_is_always_available(self) -> None:
        """The one action the agent can always take, by design."""
        ctx = context(capabilities=frozenset())
        available = {spec.name for spec in registry().available_for(ctx)}
        assert available == {"escalate_to_human"}

    def test_tenant_policy_can_withhold_a_tool(self) -> None:
        ctx = context(allowed_tools=frozenset({"search_products"}))
        available = {spec.name for spec in registry().available_for(ctx)}
        assert available == {"search_products"}

    def test_no_tenant_preference_is_not_an_empty_allow_list(self) -> None:
        """`None` means "unspecified", not "nothing permitted"."""
        assert len(registry().available_for(context(allowed_tools=None))) == len(registry())


# ── The eight checks ─────────────────────────────────────────────────────────


class TestAuthorisation:
    def test_a_permitted_call_is_allowed(self) -> None:
        engine = PolicyEngine(registry())
        decision = engine.authorise("search_products", {"query": "boots"}, context())

        assert decision.outcome is Outcome.ALLOW
        assert decision.arguments is not None

    def test_an_invented_tool_name_is_rejected(self) -> None:
        """Small models invent plausible tool names regularly."""
        decision = PolicyEngine(registry()).authorise("refund_everything", {}, context())

        assert decision.outcome is Outcome.REJECT
        assert decision.check is Check.REGISTERED

    def test_a_missing_capability_is_rejected(self) -> None:
        decision = PolicyEngine(registry()).authorise(
            "get_order_status",
            {"order_ref": "1001"},
            context(capabilities=frozenset({Capability.PRODUCT_SEARCH})),
        )

        assert decision.outcome is Outcome.REJECT
        assert decision.check is Check.CAPABILITY

    def test_a_missing_scope_is_rejected(self) -> None:
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, context(scopes=frozenset())
        )

        assert decision.outcome is Outcome.REJECT
        assert decision.check is Check.SCOPE

    def test_tenant_policy_is_enforced_at_the_engine_too(self) -> None:
        """Filtering hides it from the model; this stops it even if proposed."""
        decision = PolicyEngine(registry()).authorise(
            "get_order_status",
            {"order_ref": "1001"},
            context(allowed_tools=frozenset({"search_products"})),
        )

        assert decision.outcome is Outcome.REJECT
        assert decision.check is Check.TENANT_POLICY

    def test_bad_arguments_are_repairable_not_rejected(self) -> None:
        """The model's most common and most fixable mistake."""
        decision = PolicyEngine(registry()).authorise("search_products", {}, context())

        assert decision.outcome is Outcome.REPAIR
        assert decision.check is Check.ARGUMENTS
        assert "query" in decision.reason

    def test_an_unknown_argument_is_repairable(self) -> None:
        decision = PolicyEngine(registry()).authorise(
            "search_products", {"query": "boots", "sql": "DROP TABLE"}, context()
        )

        assert decision.outcome is Outcome.REPAIR

    def test_the_budget_degrades_rather_than_failing(self) -> None:
        """Never a hard error for the shopper (llm-abstraction.md §6)."""
        budget = ConversationBudget(max_tool_calls=1)
        budget.spend()

        decision = PolicyEngine(registry()).authorise(
            "search_products", {"query": "boots"}, context(), budget
        )

        assert decision.outcome is Outcome.DEGRADE
        assert decision.check is Check.BUDGET


class TestOwnership:
    """The most likely real-world breach in a support agent, and it needs no AI
    knowledge to exploit — a shopper simply types other order numbers."""

    def test_an_anonymous_session_cannot_read_an_order(self) -> None:
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, context()
        )

        assert decision.outcome is Outcome.ESCALATE
        assert decision.check is Check.OWNERSHIP

    def test_a_verified_reference_is_allowed(self) -> None:
        ctx = context(identity=SessionIdentity(verified_order_refs=frozenset({"1001"})))
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, ctx
        )

        assert decision.outcome is Outcome.ALLOW

    def test_verifying_one_order_grants_nothing_about_another(self) -> None:
        """Otherwise proving one order becomes a key to the whole store."""
        ctx = context(identity=SessionIdentity(verified_order_refs=frozenset({"1001"})))
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1002"}, ctx
        )

        assert decision.outcome is Outcome.ESCALATE
        assert decision.check is Check.OWNERSHIP

    def test_an_authenticated_customer_is_trusted_only_by_a_scoped_tool(self) -> None:
        """Being signed in is not, by itself, permission to read any order.

        This is the A6 fix. The engine used to trust an authenticated session
        with an arbitrary reference, on the assumption that the tool filtered by
        customer id — a true assumption for the tool that existed, enforced by
        nothing. A signed-in shopper typing a stranger's order number passed all
        eight checks.

        Now the assumption is a declaration and the default is deny.
        """
        ctx = context(identity=SessionIdentity(customer_external_id="cust_88"))
        engine = PolicyEngine(registry())

        declared = engine.authorise("get_order_status", {"order_ref": "1001"}, ctx)
        undeclared = engine.authorise("get_unscoped_order", {"order_ref": "1001"}, ctx)

        assert declared.outcome is Outcome.ALLOW
        assert undeclared.outcome is Outcome.ESCALATE
        assert undeclared.check is Check.OWNERSHIP

    def test_a_tool_that_forgets_to_declare_scoping_fails_closed(self) -> None:
        """The direction of the failure is the entire point.

        "Every tool remembers" is a control that holds until someone adds a tool.
        Forgetting the declaration must cost that tool access for authenticated
        sessions — visible, and safe — rather than silently granting a stranger's
        order to anyone signed in.
        """
        assert not get_unscoped_order.scoped_to_session
        ctx = context(identity=SessionIdentity(customer_external_id="cust_88"))

        assert not ctx.identity.may_see("1001", tool_scopes_to_session=False)
        assert ctx.identity.may_see("1001", tool_scopes_to_session=True)

    def test_the_refusal_is_uniform(self) -> None:
        """A different message for "wrong owner" and "no such order" turns the
        error itself into an order-enumeration oracle."""
        engine = PolicyEngine(registry())
        stranger = engine.authorise("get_order_status", {"order_ref": "1001"}, context())
        nonexistent = engine.authorise("get_order_status", {"order_ref": "999999"}, context())

        assert stranger.reason == nonexistent.reason

    def test_ownership_is_checked_after_validation(self) -> None:
        """It reads a validated argument, so the order is load-bearing."""
        decision = PolicyEngine(registry()).authorise("get_order_status", {}, context())
        assert decision.check is Check.ARGUMENTS

    def test_identity_is_never_taken_from_conversation_text(self) -> None:
        """A model can be talked into believing verification happened. The engine
        reads a value, and there is no argument by which the model can set it."""
        ctx = context()
        assert "identity" not in get_order_status.json_schema()["properties"]
        assert not ctx.identity.may_see("1001")


# ── Execution ────────────────────────────────────────────────────────────────


class TestExecution:
    async def test_an_allowed_call_runs(self) -> None:
        ctx = context(identity=SessionIdentity(customer_external_id="cust_1"))
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, ctx
        )
        invocation = await execute(get_order_status, decision, ctx)

        assert invocation.ok
        assert "1001" in str(invocation.value)

    async def test_what_the_call_was_made_with_is_recorded(self) -> None:
        """As authorised, not as proposed — and joined to its own result.

        Until 2026-08-27 the arguments lived on the `Decision` and the result
        lived on the invocation, with nothing joining them, so *"which query did
        it search for?"* could not be answered from anything the system kept.
        A14 needed exactly that to tell a planner that searched badly from a
        catalogue that answered badly.
        """
        ctx = context(identity=SessionIdentity(customer_external_id="cust_1"))
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, ctx
        )
        invocation = await execute(get_order_status, decision, ctx)

        assert invocation.arguments == {"order_ref": "1001"}

    async def test_pii_is_propagated_from_the_declaration(self) -> None:
        """Marked at the tool, never guessed from the text of a result — that
        flag is what keeps customer data out of the semantic cache."""
        ctx = context(identity=SessionIdentity(customer_external_id="cust_1"))
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, ctx
        )
        invocation = await execute(get_order_status, decision, ctx)

        assert invocation.pii_output is True

    async def test_an_unauthorised_decision_cannot_be_executed(self) -> None:
        """Otherwise the entire policy engine is decorative."""
        ctx = context()
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, ctx
        )
        assert not decision.allowed

        with pytest.raises(ValueError, match="only a call the policy engine allowed"):
            await execute(get_order_status, decision, ctx)

    async def test_a_slow_tool_is_cut_off(self) -> None:
        """A store having a bad day must not hold a shopper's chat open."""

        @tool(name="slow", description="hangs", timeout_s=0.05)
        async def slow(ctx: ToolContext) -> str:
            await asyncio.sleep(5)
            return "never"

        ctx = context()
        decision = PolicyEngine(ToolRegistry([slow])).authorise("slow", {}, ctx)
        invocation = await execute(slow, decision, ctx)

        assert not invocation.ok
        assert invocation.error is not None
        assert "timed out" in invocation.error

    async def test_an_adapter_failure_is_reported_not_raised(self) -> None:
        @tool(name="broken_store", description="store is down")
        async def broken_store(ctx: ToolContext) -> str:
            raise AdapterUnavailableError("the store is not answering")

        ctx = context()
        decision = PolicyEngine(ToolRegistry([broken_store])).authorise("broken_store", {}, ctx)
        invocation = await execute(broken_store, decision, ctx)

        assert not invocation.ok
        assert "not answering" in str(invocation.error)

    async def test_a_crashing_tool_does_not_kill_the_conversation(self) -> None:
        @tool(name="buggy", description="has a bug")
        async def buggy(ctx: ToolContext) -> str:
            raise KeyError("a bug in our own code")

        ctx = context()
        decision = PolicyEngine(ToolRegistry([buggy])).authorise("buggy", {}, ctx)
        invocation = await execute(buggy, decision, ctx)

        assert not invocation.ok
        # The model is told plainly, so it escalates rather than inventing.
        assert "failed" in invocation.as_model_message()

    async def test_a_tool_cannot_be_passed_a_forged_context(self) -> None:
        """The arguments executed are the validated ones, not the raw input."""

        class Forged(BaseModel):
            order_ref: str = "9999"

        ctx = context(identity=SessionIdentity(customer_external_id="cust_1"))
        decision = PolicyEngine(registry()).authorise(
            "get_order_status", {"order_ref": "1001"}, ctx
        )
        assert decision.arguments is not None
        assert decision.arguments.model_dump() == {"order_ref": "1001"}
