"""Tenancy — tenants, API keys, per-tenant configuration, budgets, metering.

Milestone 1.13. The isolation *model* landed earlier and is not repeated here:
Row-Level Security arrived with the first migration (ADR-0008) and every table
this package adds is protected by it, enforced by
``tests/integration/test_migrations.py`` rather than by a review checklist.

What this package adds is the layer above the isolation — the records that make
a tenant a thing rather than a string:

    keys.py         minting and recognising fn_sk_ / fn_pk_ tokens
    models.py       what a tenant and a key are
    schema.py       the four tables
    repository.py   reading and writing them, always tenant-scoped
    auth.py         a bearer token becomes an AuthenticatedCaller
    usage.py        what a tenant consumed, per day, per agent
    budget.py       what to do about it

It lives in ``neura-core`` because everything above needs it and it may depend on
nothing above: the API authenticates with it, the agent runtime is configured by
it, and the sync engine meters against it. Three decisions are recorded as
ADR-0013 (tenant records and configuration), ADR-0014 (API keys and the
authentication bootstrap under RLS) and ADR-0015 (metering and budgets).
"""

from neura_core.tenancy.auth import authenticate, require_agent, require_scopes
from neura_core.tenancy.budget import (
    Admission,
    BudgetLimits,
    RuntimePolicy,
    resolve_runtime_policy,
)
from neura_core.tenancy.keys import ApiKeyKind, IssuedKey, KeyEnvironment
from neura_core.tenancy.models import (
    ApiKey,
    AuthenticatedCaller,
    Tenant,
    TenantConfig,
    TenantStatus,
)
from neura_core.tenancy.modes import TurnMode, resolve_turn_mode
from neura_core.tenancy.repository import (
    ApiKeyRepository,
    StoreConnectionRepository,
    TenantRepository,
)
from neura_core.tenancy.schema import (
    api_keys,
    shop_checks,
    shop_tokens,
    tenant_stores,
    tenant_usage,
    tenants,
)
from neura_core.tenancy.shop_setup import (
    SHOP_TOKEN_PREFIX,
    ShopCheckRepository,
    ShopTokenRepository,
    new_shop_token,
)
from neura_core.tenancy.usage import UsageDelta, UsageMeter, UsageTotals

__all__ = [
    "SHOP_TOKEN_PREFIX",
    "Admission",
    "ApiKey",
    "ApiKeyKind",
    "ApiKeyRepository",
    "AuthenticatedCaller",
    "BudgetLimits",
    "IssuedKey",
    "KeyEnvironment",
    "RuntimePolicy",
    "ShopCheckRepository",
    "ShopTokenRepository",
    "StoreConnectionRepository",
    "Tenant",
    "TenantConfig",
    "TenantRepository",
    "TenantStatus",
    "TurnMode",
    "UsageDelta",
    "UsageMeter",
    "UsageTotals",
    "api_keys",
    "authenticate",
    "new_shop_token",
    "require_agent",
    "require_scopes",
    "resolve_runtime_policy",
    "resolve_turn_mode",
    "shop_checks",
    "shop_tokens",
    "tenant_stores",
    "tenant_usage",
    "tenants",
]
