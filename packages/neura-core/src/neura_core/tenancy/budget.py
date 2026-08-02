"""Budgets — and what a tenant's runtime looks like once one bites.

The ladder is from security-model.md §7 and llm-abstraction.md §6, and its whole
point is in the last row:

    spend < soft        NORMAL          nothing changes
    soft ≤ spend < hard DEGRADED        fewer tool calls per turn
    hard ≤ spend        ESCALATE_ONLY   no tools; every turn reaches a person

**No rung is an error.** A shopper who hits a merchant's ceiling gets a human,
not a 500 and not "we are unable to process your request". An attacker looping
an agent through expensive tool calls gets the same handover, which is the
cheapest possible outcome for us and an acceptable one for them.

**Escalate-only needs no new code in the agent.** It is expressed as an empty
tool allowlist, which check 4 of the policy engine already enforces and which
CARE already handles by handing over — the same mechanism a merchant uses to
disable one tool, with the set taken to its limit. A new "budget exhausted"
branch in the graph would be a second path to test, a second path to get wrong,
and a behaviour change that the golden suite would have to be re-run to trust.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from neura_core.config import Settings, get_settings
from neura_core.errors import AgentNotEnabledError
from neura_core.tenancy.models import Tenant


class Admission(StrEnum):
    """How much of the system this tenant may use right now."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    ESCALATE_ONLY = "escalate_only"


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    """One tenant's daily ceilings, in US dollars."""

    soft: Decimal
    hard: Decimal

    @classmethod
    def resolve(cls, tenant: Tenant, settings: Settings | None = None) -> BudgetLimits:
        """Tenant configuration where set, platform defaults where not.

        A tenant that has never been configured therefore behaves exactly as the
        system did before tenancy existed — which is what makes this milestone
        safe to land without re-measuring the agent.
        """
        defaults = settings or get_settings()
        soft = tenant.config.daily_cost_usd_soft
        hard = tenant.config.daily_cost_usd_hard
        return cls(
            soft=soft if soft is not None else Decimal(str(defaults.budget_daily_cost_usd_soft)),
            hard=hard if hard is not None else Decimal(str(defaults.budget_daily_cost_usd_hard)),
        )

    def admit(self, spend_usd: Decimal) -> Admission:
        # Hard first: a misconfiguration with hard below soft must fail towards
        # the safer rung rather than towards spending money.
        if spend_usd >= self.hard:
            return Admission.ESCALATE_ONLY
        if spend_usd >= self.soft:
            return Admission.DEGRADED
        return Admission.NORMAL


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    """Everything tenancy decides about one conversation before it starts.

    Handed to whatever assembles the agent runtime. Deliberately expressed in
    values the runtime already accepts — an allowlist and a ceiling — so that
    tenancy stays a *caller* of the agent rather than something the agent has to
    know about. ``neura_agent_core`` never learns that tenants have budgets, for
    the same reason it never learns an agent's name.
    """

    tenant_id: str
    agent_key: str
    admission: Admission
    #: ``None`` means every registered tool; the empty set means none of them.
    allowed_tools: frozenset[str] | None
    max_tool_calls: int
    spend_usd: Decimal
    limits: BudgetLimits

    @property
    def is_escalate_only(self) -> bool:
        return self.admission is Admission.ESCALATE_ONLY

    def runtime_kwargs(self) -> dict[str, object]:
        """The ceilings, as the keyword arguments an agent runtime takes.

            build_runtime(tenant_id=…, adapter=…, **policy.runtime_kwargs())

        A method rather than prose in a document, because the alternative is
        every caller re-deriving the mapping and one of them getting it wrong in
        the direction that spends money. It is deliberately not a dependency in
        the other direction: nothing in ``agents/`` or ``neura_agent_core``
        imports this module.
        """
        return {"allowed_tools": self.allowed_tools, "max_tool_calls": self.max_tool_calls}


def resolve_runtime_policy(
    tenant: Tenant,
    agent_key: str,
    spend_usd: Decimal,
    *,
    settings: Settings | None = None,
) -> RuntimePolicy:
    """Entitlement, then budget, then the resulting ceilings.

    Raises :class:`AgentNotEnabledError` when the tenant has not bought this
    agent — an entitlement, not a bug (tenancy-and-packaging.md §3). Checking it
    here rather than in each caller is what stops one route forgetting.
    """
    if not tenant.may_use(agent_key):
        raise AgentNotEnabledError(
            f"{agent_key} is not enabled for this account.",
            details={"agent": agent_key, "status": tenant.status.value},
        )

    defaults = settings or get_settings()
    limits = BudgetLimits.resolve(tenant, defaults)
    admission = limits.admit(spend_usd)
    config = tenant.config

    normal_calls = (
        config.max_tool_calls
        if config.max_tool_calls is not None
        else defaults.budget_turn_max_tool_calls
    )

    if admission is Admission.ESCALATE_ONLY:
        allowed_tools: frozenset[str] | None = frozenset()
        max_tool_calls = 0
    elif admission is Admission.DEGRADED:
        allowed_tools = config.allowed_tools
        max_tool_calls = min(config.degraded_max_tool_calls, normal_calls)
    else:
        allowed_tools = config.allowed_tools
        max_tool_calls = normal_calls

    return RuntimePolicy(
        tenant_id=tenant.tenant_id,
        agent_key=agent_key,
        admission=admission,
        allowed_tools=allowed_tools,
        max_tool_calls=max_tool_calls,
        spend_usd=spend_usd,
        limits=limits,
    )
