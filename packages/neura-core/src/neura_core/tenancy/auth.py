"""Turning a bearer token into a tenant.

This is the only place in the system where the tenant is *decided*. Everything
downstream — the RLS session variable, the vector namespace, the Redis prefix,
the audit row, the tool context — is derived from what this function returns, so
a mistake here is not one bug among many.

**The bootstrap problem, and why it is not solved with an exemption.** The tenant
comes from the key, so the row identifying the tenant must be read by a
transaction that cannot yet name one — and under ADR-0008 such a transaction
sees nothing. The usual shortcut is to leave ``api_keys`` outside Row-Level
Security as a "control plane" table; that quietly creates the one table where a
forgotten ``WHERE tenant_id`` leaks every merchant's credentials at once, and the
test that would catch it is the test the shortcut disables.

Instead the key's own hash is the capability: the credential session sets
``app.api_key_hash``, the policy on ``api_keys`` grants read access to the row
whose hash equals it, and the transaction is ``READ ONLY``. A caller may learn
about the credential they already hold and nothing else (ADR-0014).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from neura_core.db import Database
from neura_core.errors import AgentNotEnabledError, AuthenticationError, ForbiddenError
from neura_core.logging import get_logger
from neura_core.tenancy import keys
from neura_core.tenancy.models import ApiKey, AuthenticatedCaller, Tenant
from neura_core.tenancy.repository import ApiKeyRepository, TenantRepository

log = get_logger(__name__)

#: How stale ``last_used_at`` is allowed to get. The column answers "has anyone
#: used this key in months?", so minute-level precision is worth nothing and a
#: write per request is worth avoiding.
LAST_USED_GRANULARITY = timedelta(minutes=5)

#: One message for "we do not recognise this key". Malformed and unknown must
#: read identically: a distinguishable response tells someone probing which of
#: their guesses had the right shape.
_UNKNOWN = "Invalid API key."


async def authenticate(
    db: Database,
    token: str,
    *,
    origin: str | None = None,
    now: datetime | None = None,
) -> AuthenticatedCaller:
    """Authenticate a presented key. Raises rather than returning ``None``.

    Five things have to be true, and each failure is deliberate about how much
    it says. A caller who does not hold a valid key learns nothing; a caller who
    does — the merchant — is told plainly what is wrong with it, because they
    already possess the credential and the alternative is a support ticket.
    """
    moment = now or datetime.now(UTC)

    if not keys.is_well_formed(token):
        # No database round trip for a pasted password or an empty header.
        raise AuthenticationError(_UNKNOWN)

    async with db.credential_session(keys.fingerprint(token)) as session:
        api_key = await ApiKeyRepository(session).find_by_token(token)

    if api_key is None:
        raise AuthenticationError(_UNKNOWN)

    if api_key.revoked_at is not None:
        raise AuthenticationError("This API key has been revoked.")

    if not api_key.is_usable(moment):
        raise AuthenticationError("This API key has expired.")

    if not api_key.permits_origin(origin):
        # Public keys only. The message names the control rather than the
        # allowlist: echoing the permitted origins back would turn a rejected
        # request into a way to read the merchant's configuration.
        raise ForbiddenError(
            "This key is not permitted from that origin.",
            code="ORIGIN_NOT_ALLOWED",
            details={"origin": origin or ""},
        )

    async with db.tenant_session(api_key.tenant_id) as session:
        tenant = await TenantRepository(session).get(api_key.tenant_id)
        if tenant is None:
            # A key whose tenant row is gone. Refused rather than reconstructed:
            # a caller with no tenant record has no entitlements, no budget and
            # no configuration, and guessing any of them is worse than stopping.
            raise AuthenticationError(_UNKNOWN)

        if not tenant.is_servable:
            raise ForbiddenError(
                f"This account is {tenant.status.value}.",
                code="TENANT_NOT_ACTIVE",
                details={"status": tenant.status.value},
            )

        await ApiKeyRepository(session).touch(
            api_key.id, at=moment, not_before=moment - LAST_USED_GRANULARITY
        )

    log.info(
        "api_key_authenticated",
        tenant_id=tenant.tenant_id,
        key_id=api_key.id,
        key_prefix=api_key.token_prefix,
        kind=api_key.kind.value,
    )
    return AuthenticatedCaller(tenant=tenant, api_key=api_key)


def require_scopes(caller: AuthenticatedCaller, *required: str) -> None:
    """Refuse a caller whose key does not hold every named scope.

    Separate from :func:`authenticate` because scope requirements belong to the
    route, not to the credential — and because the policy engine checks scopes
    again at the tool boundary. Two checks, deliberately: this one gives a clean
    403 before any work happens, and that one is the security boundary.
    """
    missing = sorted(set(required) - caller.scopes)
    if missing:
        raise ForbiddenError(
            "This API key does not hold the required scope.",
            details={"missing_scopes": missing},
        )


def require_agent(caller: AuthenticatedCaller, agent_key: str) -> None:
    """Refuse a caller whose tenant has not bought this agent.

    ``AGENT_NOT_ENABLED`` is an entitlement, not a bug — see
    tenancy-and-packaging.md §3 and the gotcha table in AGENTS.md.
    """
    if not caller.may_use(agent_key):
        raise AgentNotEnabledError(
            f"{agent_key} is not enabled for this account.",
            details={"agent": agent_key},
        )


__all__ = [
    "LAST_USED_GRANULARITY",
    "ApiKey",
    "AuthenticatedCaller",
    "Tenant",
    "authenticate",
    "require_agent",
    "require_scopes",
]
