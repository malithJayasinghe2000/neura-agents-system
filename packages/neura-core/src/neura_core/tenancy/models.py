"""What a tenant and an API key *are*, independently of how they are stored.

Pydantic rather than raw rows, for the usual boundary reason: these values cross
from the database into request handling, agent assembly and the audit log, and a
dict that has been passed through four layers is a dict nobody can typecheck.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from neura_core.tenancy.keys import ApiKeyKind
from neura_core.tenancy.modes import TurnMode, coerce_mode


class TenantStatus(StrEnum):
    ACTIVE = "active"
    """Serving normally."""

    SUSPENDED = "suspended"
    """Non-payment, abuse, or an incident. Authentication fails closed."""

    OFFBOARDING = "offboarding"
    """Leaving. Still readable so their data can be exported and purged, but no
    longer served — an offboarding tenant's shoppers must not reach an agent
    whose store connection is about to be deleted."""


class TenantConfig(BaseModel):
    """Per-tenant behaviour a merchant may change without a deploy.

    **Every field here is read by something.** A knob nothing consults is a
    setting that appears to work, and this project has already recorded that
    failure twice — a `pii_leaked` assertion scored by nothing for two
    milestones, and `guard.block` events nobody reads (S5). Retention days,
    plan names and locales are deliberately absent until the code that honours
    them exists.

    ``None`` means "use the platform default from ``Settings``", which is how a
    tenant that has never been configured behaves exactly like the system did
    before it existed.
    """

    # Unknown keys are ignored rather than rejected: a config written by a newer
    # deployment must not make a rolled-back one fail to read its own tenants.
    model_config = ConfigDict(extra="ignore")

    daily_cost_usd_soft: Decimal | None = Field(
        default=None,
        description="Spend at which this tenant degrades to cheaper behaviour.",
    )
    daily_cost_usd_hard: Decimal | None = Field(
        default=None,
        description="Spend at which this tenant is escalate-only for the rest of the day.",
    )
    max_tool_calls: int | None = Field(
        default=None,
        description="Tool-call ceiling for one turn. Overrides the platform default.",
    )
    degraded_max_tool_calls: int = Field(
        default=2,
        ge=0,
        description="The ceiling once the soft budget is passed.",
    )
    allowed_tools: frozenset[str] | None = Field(
        default=None,
        description=(
            "Tenant tool allowlist — check 4 of the policy engine. `None` means "
            "every registered tool; an empty set means none of them."
        ),
    )
    mode: TurnMode = Field(
        default=TurnMode.LIVE,
        description=(
            "Does the shopper read the agent's reply? `shadow` runs the whole turn "
            "and shows the shopper nothing (agent-runtime.md §6)."
        ),
    )
    shadow_intents: frozenset[str] = Field(
        default=frozenset(),
        description=(
            "Intents shadowed even while the tenant is live. This is the per-intent "
            "half of §6 — live for order status, watched for returns policy."
        ),
    )
    withheld_message: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "What a shopper is shown when the reply is withheld — a shadowed turn "
            "(ADR-0020). `None` uses the platform default. It must not claim a "
            "person was told: no webhook fires on a shadow turn and there is no "
            "console for anyone to be watching."
        ),
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _mode_falls_back_to_shadow(cls, value: object) -> object:
        """An unreadable mode withholds rather than defaults — see ``modes.py``.

        ``before``, deliberately: by the time Pydantic has rejected
        ``"supervised"`` as an invalid enum member the whole tenant has failed to
        load, and a tenant that cannot be read cannot be served at all.
        """
        return TurnMode.LIVE if value is None else coerce_mode(value)


class Tenant(BaseModel):
    """One merchant."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    name: str
    status: TenantStatus = TenantStatus.ACTIVE
    #: The entitlement layer (tenancy-and-packaging.md §3). An agent absent from
    #: this set does not exist as far as this tenant is concerned — not
    #: disabled, not shown locked: absent.
    enabled_agents: frozenset[str] = frozenset()
    config: TenantConfig = TenantConfig()
    #: When a data-processing agreement was recorded; ``None`` means none
    #: exists (ADR-0042 §2).
    dpa_signed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_servable(self) -> bool:
        return self.status is TenantStatus.ACTIVE

    @property
    def may_hold_personal_data(self) -> bool:
        """ADR-0042 §2's precondition: an agreement is recorded.

        Necessary, never sufficient — a feature that stores personal data still
        needs its own ADR and its own switch.
        """
        return self.dpa_signed_at is not None

    def may_use(self, agent_key: str) -> bool:
        """Has this tenant bought this agent?

        Both halves matter: a suspended tenant with CARE enabled must still be
        refused, or suspension is a label rather than a control.
        """
        return self.is_servable and agent_key in self.enabled_agents


class ApiKey(BaseModel):
    """An issued key, minus the one part that is never stored."""

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    kind: ApiKeyKind
    name: str = ""
    #: Displayable fragment, e.g. ``fn_sk_live_x7Kq2mBv``. Never the whole key.
    token_prefix: str
    scopes: frozenset[str] = frozenset()
    #: Only meaningful for public keys, which are readable by anyone who loads
    #: the merchant's page.
    allowed_origins: tuple[str, ...] = ()
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None

    def is_usable(self, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        if self.revoked_at is not None:
            return False
        return not (self.expires_at is not None and self.expires_at <= moment)

    def permits_origin(self, origin: str | None) -> bool:
        """Secret keys are not origin-locked; public keys always are.

        An empty allowlist on a public key permits **nothing**. That is the
        deliberate direction for an access control to fail: a widget key issued
        without origins is inert until someone configures it, rather than open
        to every site on the internet until someone notices.
        """
        if self.kind is ApiKeyKind.SECRET:
            return True
        return origin is not None and origin in self.allowed_origins


class AuthenticatedCaller(BaseModel):
    """The outcome of authentication: who is calling, and what they may do.

    Everything the policy engine treats as unforgeable — tenant, scopes,
    entitlements — arrives in this object and in no other way. No prompt, no
    request body and no model output contributes to it (AGENTS.md rule 3).
    """

    model_config = ConfigDict(frozen=True)

    tenant: Tenant
    api_key: ApiKey

    @property
    def tenant_id(self) -> str:
        return self.tenant.tenant_id

    @property
    def scopes(self) -> frozenset[str]:
        return self.api_key.scopes

    def may_use(self, agent_key: str) -> bool:
        return self.tenant.may_use(agent_key)
