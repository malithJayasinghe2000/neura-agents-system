"""Tenancy without a database — key format, entitlements, budgets, metering.

The parts that need real PostgreSQL are in
``tests/integration/test_tenancy_postgres.py``, and they are the ones that
matter most: isolation is a property of the database, and a fake that "proves"
it proves only that the fake filters.

What is testable here is everything that decides *what the database will be
asked for* — and two of those decisions are security controls in their own
right: a public key with no origin allowlist must permit nothing, and a tenant
over its hard ceiling must end up with no tools rather than with an error.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from neura_core.config import Settings
from neura_core.errors import AgentNotEnabledError, AuthenticationError
from neura_core.logging import _redact
from neura_core.tenancy import keys
from neura_core.tenancy.auth import authenticate
from neura_core.tenancy.budget import (
    Admission,
    BudgetLimits,
    resolve_runtime_policy,
)
from neura_core.tenancy.keys import ApiKeyKind, KeyEnvironment
from neura_core.tenancy.models import (
    ApiKey,
    AuthenticatedCaller,
    Tenant,
    TenantConfig,
    TenantStatus,
)
from neura_core.tenancy.schema import tenant_usage
from neura_core.tenancy.usage import COUNTERS, UsageDelta

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

SETTINGS = Settings(
    BUDGET_DAILY_COST_USD_SOFT=8.0,
    BUDGET_DAILY_COST_USD_HARD=12.0,
    BUDGET_TURN_MAX_TOOL_CALLS=4,
)


def tenant(**overrides: Any) -> Tenant:
    defaults: dict[str, Any] = {
        "tenant_id": "tn_test",
        "name": "Test Merchant",
        "enabled_agents": frozenset({"care"}),
    }
    return Tenant(**{**defaults, **overrides})


def api_key(**overrides: Any) -> ApiKey:
    defaults: dict[str, Any] = {
        "id": "key_test",
        "tenant_id": "tn_test",
        "kind": ApiKeyKind.SECRET,
        "token_prefix": "fn_sk_test_abcd1234",
        "scopes": frozenset({"care:chat:write"}),
    }
    return ApiKey(**{**defaults, **overrides})


class TestKeyFormat:
    def test_minted_key_is_recognisable_and_parses_back(self) -> None:
        issued = keys.generate(ApiKeyKind.SECRET, KeyEnvironment.LIVE)

        assert issued.token.startswith("fn_sk_live_")
        assert keys.parse(issued.token) == (
            ApiKeyKind.SECRET,
            KeyEnvironment.LIVE,
            issued.token.removeprefix("fn_sk_live_"),
        )

    def test_random_part_carries_256_bits(self) -> None:
        """Everything else in this module rests on this number."""
        _, _, random_part = keys.parse(keys.generate().token) or (None, None, "")
        assert len(random_part) >= 43

    def test_two_keys_never_collide(self) -> None:
        tokens = {keys.generate().token for _ in range(200)}
        assert len(tokens) == 200

    def test_prefix_is_displayable_and_not_the_key(self) -> None:
        issued = keys.generate(ApiKeyKind.PUBLIC, KeyEnvironment.TEST)

        assert issued.token.startswith(issued.token_prefix)
        # The stored fragment must not be enough to authenticate with.
        assert len(issued.token_prefix) < len(issued.token)
        assert not keys.matches(issued.token_prefix, issued.token_hash)

    def test_hash_is_stable_and_one_way(self) -> None:
        issued = keys.generate()

        assert keys.fingerprint(issued.token) == issued.token_hash
        assert issued.token not in issued.token_hash
        assert keys.matches(issued.token, issued.token_hash)
        assert not keys.matches(issued.token + "x", issued.token_hash)

    @pytest.mark.parametrize(
        "junk",
        [
            "",
            "   ",
            "hunter2",
            "Bearer fn_sk_live_abc",
            "fn_sk_live_",
            "fn_xx_live_abcdefghijklmnopqrstuvwx",
            "fn_sk_prod_abcdefghijklmnopqrstuvwx",
            "sk_live_abcdefghijklmnopqrstuvwxyz",
        ],
    )
    def test_junk_is_rejected_without_a_query(self, junk: str) -> None:
        """The shape check exists so a pasted password costs a regex, not a
        round trip to the database."""
        assert not keys.is_well_formed(junk)

    def test_a_leaked_key_is_scrubbed_from_logs(self) -> None:
        """The format and the redaction filter have to agree, or the filter is
        protecting a shape we no longer mint."""
        issued = keys.generate()
        assert issued.token not in _redact(f"auth failed for {issued.token}", "detail")


class TestEntitlements:
    def test_an_unbought_agent_is_refused(self) -> None:
        assert not tenant().may_use("sell")
        assert tenant().may_use("care")

    def test_a_suspended_tenant_is_refused_every_agent(self) -> None:
        """Suspension has to outrank entitlement, or it is a label rather than
        a control."""
        suspended = tenant(status=TenantStatus.SUSPENDED)
        assert not suspended.may_use("care")

    def test_offboarding_is_readable_but_not_servable(self) -> None:
        leaving = tenant(status=TenantStatus.OFFBOARDING)
        assert not leaving.is_servable
        assert not leaving.may_use("care")

    def test_resolve_refuses_an_agent_the_tenant_has_not_bought(self) -> None:
        with pytest.raises(AgentNotEnabledError):
            resolve_runtime_policy(tenant(), "sell", Decimal("0"), settings=SETTINGS)


class TestApiKeyUsability:
    def test_revoked_and_expired_keys_are_unusable(self) -> None:
        assert not api_key(revoked_at=NOW).is_usable(NOW)
        assert not api_key(expires_at=NOW - timedelta(seconds=1)).is_usable(NOW)
        assert api_key(expires_at=NOW + timedelta(days=1)).is_usable(NOW)

    def test_a_public_key_without_origins_permits_nothing(self) -> None:
        """The direction an access control must fail in: inert until
        configured, never open until noticed."""
        widget = api_key(kind=ApiKeyKind.PUBLIC, allowed_origins=())

        assert not widget.permits_origin("https://shop.example")
        assert not widget.permits_origin(None)

    def test_a_public_key_is_locked_to_its_origins(self) -> None:
        widget = api_key(kind=ApiKeyKind.PUBLIC, allowed_origins=("https://shop.example",))

        assert widget.permits_origin("https://shop.example")
        assert not widget.permits_origin("https://evil.example")

    def test_a_secret_key_is_not_origin_locked(self) -> None:
        assert api_key().permits_origin(None)


class TestBudgetLadder:
    @pytest.mark.parametrize(
        ("spend", "expected"),
        [
            ("0", Admission.NORMAL),
            ("7.99", Admission.NORMAL),
            ("8", Admission.DEGRADED),
            ("11.99", Admission.DEGRADED),
            ("12", Admission.ESCALATE_ONLY),
            ("40", Admission.ESCALATE_ONLY),
        ],
    )
    def test_the_three_rungs(self, spend: str, expected: Admission) -> None:
        limits = BudgetLimits(soft=Decimal("8"), hard=Decimal("12"))
        assert limits.admit(Decimal(spend)) is expected

    def test_a_misconfigured_ceiling_fails_towards_the_safer_rung(self) -> None:
        """Hard below soft is a mistake either way; spending money is the worse
        way to resolve it."""
        limits = BudgetLimits(soft=Decimal("10"), hard=Decimal("5"))
        assert limits.admit(Decimal("7")) is Admission.ESCALATE_ONLY

    def test_tenant_limits_override_platform_defaults(self) -> None:
        configured = tenant(
            config=TenantConfig(daily_cost_usd_soft=Decimal("1"), daily_cost_usd_hard=Decimal("2"))
        )
        assert BudgetLimits.resolve(configured, SETTINGS) == BudgetLimits(
            soft=Decimal("1"), hard=Decimal("2")
        )

    def test_an_unconfigured_tenant_uses_the_platform_defaults(self) -> None:
        """The property that makes this milestone safe to land: a tenant with no
        configuration behaves exactly as the system did before tenancy."""
        assert BudgetLimits.resolve(tenant(), SETTINGS) == BudgetLimits(
            soft=Decimal("8"), hard=Decimal("12")
        )


class TestRuntimePolicy:
    def test_normal_spend_changes_nothing(self) -> None:
        policy = resolve_runtime_policy(tenant(), "care", Decimal("0"), settings=SETTINGS)

        assert policy.admission is Admission.NORMAL
        assert policy.allowed_tools is None
        assert policy.max_tool_calls == 4

    def test_the_soft_ceiling_lowers_the_tool_ceiling(self) -> None:
        policy = resolve_runtime_policy(tenant(), "care", Decimal("9"), settings=SETTINGS)

        assert policy.admission is Admission.DEGRADED
        assert policy.max_tool_calls == 2
        assert policy.allowed_tools is None

    def test_the_hard_ceiling_is_an_empty_allowlist_not_an_error(self) -> None:
        """Escalate-only reuses check 4 of the policy engine rather than adding a
        branch to the graph: no tool is permitted, so every turn reaches a
        person, and no shopper sees a failure."""
        policy = resolve_runtime_policy(tenant(), "care", Decimal("99"), settings=SETTINGS)

        assert policy.is_escalate_only
        assert policy.allowed_tools == frozenset()
        assert policy.max_tool_calls == 0

    def test_a_tenant_allowlist_survives_degradation(self) -> None:
        configured = tenant(config=TenantConfig(allowed_tools=frozenset({"search_policies"})))
        policy = resolve_runtime_policy(configured, "care", Decimal("9"), settings=SETTINGS)

        assert policy.allowed_tools == frozenset({"search_policies"})

    def test_degrading_never_raises_the_ceiling(self) -> None:
        """A tenant whose normal ceiling is already below the degraded one must
        not be *granted* tool calls by going over budget."""
        frugal = tenant(config=TenantConfig(max_tool_calls=1, degraded_max_tool_calls=3))
        policy = resolve_runtime_policy(frugal, "care", Decimal("9"), settings=SETTINGS)

        assert policy.max_tool_calls == 1


class TestPolicyReachesTheAgent:
    """The claim in budget.py is that escalate-only needs no new code in the
    agent. These prove it rather than asserting it — a real CARE runtime,
    assembled from a real policy, refusing a real tool."""

    def _runtime(self, spend: str):
        from neura_agent_care.runtime import build_runtime
        from neura_domain import Capability

        policy = resolve_runtime_policy(tenant(), "care", Decimal(spend), settings=SETTINGS)
        return policy, build_runtime(
            tenant_id="tn_test",
            conversation_id="cnv_test",
            adapter=None,
            llm=None,
            capabilities=frozenset(Capability),
            scopes=frozenset({"care:order:read"}),
            **policy.runtime_kwargs(),  # type: ignore[arg-type]
        )

    def test_the_kwargs_are_the_ones_the_runtime_actually_takes(self) -> None:
        """Catches the rename that would make a budget silently stop applying."""
        _, runtime = self._runtime("0")

        assert runtime.ctx.allowed_tools is None
        assert runtime.budget.max_tool_calls == 4

    def test_over_the_hard_ceiling_every_tool_is_refused(self) -> None:
        from neura_agent_core.policy import Check, Outcome

        _, runtime = self._runtime("99")
        decision = runtime.policy.authorise(
            "get_order_status", {"order_ref": "1001"}, runtime.ctx, runtime.budget
        )

        assert decision.outcome is Outcome.REJECT
        assert decision.check is Check.TENANT_POLICY
        # No tool available means the graph hands over — the existing path, not
        # a new one.
        assert runtime.policy.available(runtime.ctx) == []


class TestUsageDelta:
    def test_deltas_add_field_by_field(self) -> None:
        total = UsageDelta(turns=1, llm_calls=3, cost_usd=Decimal("0.02")) + UsageDelta(
            turns=1, llm_calls=2, escalations=1, cost_usd=Decimal("0.03")
        )

        assert (total.turns, total.llm_calls, total.escalations) == (2, 5, 1)
        assert total.cost_usd == Decimal("0.05")

    def test_an_empty_delta_is_recognised(self) -> None:
        """A no-op turn must not cost a write."""
        assert UsageDelta().is_empty
        assert not UsageDelta(turns=1).is_empty
        assert not UsageDelta(cost_usd=Decimal("0.0001")).is_empty

    def test_every_counter_column_is_actually_summed(self) -> None:
        """The failure this catches: a column added to the schema and forgotten
        in ``COUNTERS`` would silently never be recorded — a bill that is quietly
        too low, which nobody reports."""
        columns = {
            column.name
            for column in tenant_usage.columns
            if column.name not in {"tenant_id", "usage_date", "agent_key", "cost_usd", "updated_at"}
        }
        assert columns == set(COUNTERS)


class TestAuthenticationShapeCheck:
    async def test_a_malformed_token_never_reaches_the_database(self) -> None:
        """``None`` as the database is the assertion: if this call touched it,
        the test would raise ``AttributeError`` instead."""
        with pytest.raises(AuthenticationError):
            await authenticate(None, "hunter2")  # type: ignore[arg-type]

    async def test_the_rejection_says_nothing_about_why(self) -> None:
        with pytest.raises(AuthenticationError) as exc:
            await authenticate(None, "")  # type: ignore[arg-type]
        assert str(exc.value) == "Invalid API key."


class TestAuthenticatedCaller:
    def test_scopes_and_entitlements_come_from_the_record(self) -> None:
        caller = AuthenticatedCaller(tenant=tenant(), api_key=api_key())

        assert caller.tenant_id == "tn_test"
        assert caller.scopes == frozenset({"care:chat:write"})
        assert caller.may_use("care")
        assert not caller.may_use("sell")


class TestTenantConfig:
    def test_unknown_keys_are_ignored_rather_than_fatal(self) -> None:
        """A config written by a newer deployment must not stop an older one
        reading its own tenants."""
        config = TenantConfig.model_validate({"max_tool_calls": 3, "future_knob": "x"})
        assert config.max_tool_calls == 3

    def test_defaults_are_all_deferred_to_the_platform(self) -> None:
        config = TenantConfig()
        assert config.daily_cost_usd_soft is None
        assert config.daily_cost_usd_hard is None
        assert config.max_tool_calls is None
        assert config.allowed_tools is None
