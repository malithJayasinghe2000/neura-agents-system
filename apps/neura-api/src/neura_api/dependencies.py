"""Turning an HTTP request into an authenticated caller.

**This is where 1.13's authentication stops being wired to nothing.**
``neura_core.tenancy.authenticate`` has worked and been tested against real
PostgreSQL since that milestone, and no request path called it. Everything
downstream of this module — the RLS session variable, the tenant's ceilings, the
usage row, the audit entry, the tool context — is derived from what these
dependencies return, so a mistake here is not one bug among many.

Three checks, deliberately separate, because they answer different questions and
fail with different words:

* :func:`caller` — *is this a real, usable credential?* 401 if not.
* :func:`require` — *does this key hold the scope this route needs?* 403.
* the agent dependency — *has this tenant bought this agent?* 403
  ``AGENT_NOT_ENABLED``, which is an entitlement and not a bug
  (tenancy-and-packaging.md §3).
* :func:`acting_for` — the console's equivalent, and the only one that
  authenticates a **person**: cookie → user → membership → tenant
  ([ADR-0026](../../../../docs/architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) §3).

None of them is the security boundary. The policy engine authorises every tool
call again, in code, at the point of use. These exist so a caller gets a clean
refusal before any work happens — and so the refusal names something they can
act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from starlette.websockets import WebSocket

from neura_core import (
    AuthenticationError,
    Database,
    ForbiddenError,
    NotFoundError,
    get_database,
    get_logger,
    get_settings,
)

# Aliased on import: `verify` in this repository otherwise reads as the
# groundedness check the agent graph runs, which is an entirely different
# thing to find in an authentication path.
from neura_core.identity import COOKIE_NAME, memberships_for
from neura_core.identity import verify as verify_session
from neura_core.tenancy import AuthenticatedCaller, authenticate, require_agent, require_scopes

log = get_logger(__name__)

BEARER = "bearer"


def bearer_token(authorization: str | None) -> str:
    """Pull the token out of an ``Authorization`` header.

    A missing, malformed or non-bearer header reads identically to an unknown
    key. A distinguishable response tells someone probing which of their guesses
    had the right shape, and the merchant who typed the header wrong is helped
    by the documentation rather than by an oracle.
    """
    if not authorization:
        raise AuthenticationError("Missing Authorization header. Use `Bearer fn_sk_...`.")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != BEARER or not token.strip():
        raise AuthenticationError("Invalid API key.")
    return token.strip()


def client_address(request: Request | WebSocket) -> str:
    """The network peer, honouring exactly as many proxies as are configured.

    ``X-Forwarded-For`` is attacker-controlled. With ``NEURA_TRUSTED_PROXY_HOPS``
    at its default of 0 it is ignored entirely and the socket peer is used;
    otherwise the *n*-th entry from the right is taken, which is the last hop
    this deployment's own infrastructure appended. Anything else lets a caller
    rotate the narrowest rate-limit subject at will while the limiter carries on
    reporting plausible numbers (ADR-0017 §2).
    """
    from neura_core import get_settings

    hops = get_settings().trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= hops:
            return chain[-hops]

    peer = getattr(request, "client", None)
    return getattr(peer, "host", "") or "unknown"


async def authenticate_request(
    request: Request | WebSocket,
    *,
    token: str | None = None,
) -> AuthenticatedCaller:
    """Authenticate one request. Shared by REST and WebSocket, on purpose.

    The socket handshake carries its credential in a query parameter rather than
    a header, because browsers give a ``WebSocket`` constructor no way to set
    one. That is the *only* difference the two transports are allowed to have —
    everything after this line is identical, which is what keeps api-design.md
    §8's "the transport is never allowed to become a second code path" true.
    """
    presented = token or bearer_token(request.headers.get("authorization"))

    caller = await authenticate(
        get_database(),
        presented,
        # Only public keys are origin-locked, and only they consult this. A
        # missing Origin header on an `fn_pk_` request is a refusal, because an
        # empty allowlist permits nothing (ADR-0014 §3).
        origin=request.headers.get("origin"),
    )
    state = getattr(request, "state", None)
    if state is not None:
        state.caller = caller
    return caller


async def caller(request: Request) -> AuthenticatedCaller:
    """FastAPI dependency: the authenticated caller behind this request."""
    return await authenticate_request(request)


CallerDep = Annotated[AuthenticatedCaller, Depends(caller)]


def require(*scopes: str) -> Any:
    """A dependency that additionally demands scopes.

        @router.post("/chat", dependencies=[Depends(require("care:chat:write"))])

    Written as a factory so the scope a route needs is stated *on the route*.
    A central table mapping paths to scopes is a table that drifts from the
    routes it describes, and the drift is invisible until a key that should have
    been refused is not.
    """

    async def _dependency(request: Request) -> AuthenticatedCaller:
        authenticated = await authenticate_request(request)
        require_scopes(authenticated, *scopes)
        return authenticated

    return _dependency


@dataclass(frozen=True, slots=True)
class AgentContext:
    """An authenticated caller, plus the agent they are addressing."""

    caller: AuthenticatedCaller
    agent_key: str
    runner: Any
    manifest: Any

    @property
    def tenant_id(self) -> str:
        return self.caller.tenant_id


def resolve_agent(request: Request | WebSocket, agent_key: str) -> tuple[Any, Any]:
    """Find an installed agent's runner and manifest, or 404.

    Discovery happened at startup and lives on ``app.state``; this is a lookup,
    not a load. An agent named in a URL that this deployment does not have
    installed is a ``404`` — a different thing from an agent the *tenant* has
    not bought, which is a ``403``. Collapsing the two would tell an anonymous
    caller which agents a merchant pays for.
    """
    agents = getattr(request.app.state, "agents", {})
    runners = getattr(request.app.state, "runners", {})

    manifest = agents.get(agent_key)
    if manifest is None:
        raise NotFoundError("No such agent.", details={"agent": agent_key})

    runner = runners.get(agent_key)
    if runner is None:
        # Installed but not runnable: the package declares `neura.agents` and
        # not `neura.agent_runners`. Reported as unavailable rather than absent,
        # because "we have it and it is broken" and "we do not have it" call for
        # different actions from whoever is on call.
        raise ForbiddenError(
            "That agent is installed but cannot serve requests in this deployment.",
            code="AGENT_NOT_RUNNABLE",
            details={"agent": agent_key},
        )
    return runner, manifest


async def agent_context(
    request: Request,
    agent_key: str,
    *,
    scopes: tuple[str, ...] = (),
) -> AgentContext:
    """Authenticate, check scopes, check the entitlement, resolve the agent."""
    runner, manifest = resolve_agent(request, agent_key)
    authenticated = await authenticate_request(request)
    if scopes:
        require_scopes(authenticated, *scopes)
    require_agent(authenticated, agent_key)
    return AgentContext(caller=authenticated, agent_key=agent_key, runner=runner, manifest=manifest)


async def agent_context_for_socket(
    websocket: WebSocket,
    agent_key: str,
    *,
    token: str | None,
    scopes: tuple[str, ...] = (),
) -> AgentContext:
    """The same four checks, for a connection that has no ``Authorization`` header.

    A browser's ``WebSocket`` constructor cannot set headers, so the credential
    arrives as a query parameter — which is why ``fn_pk_`` keys are origin-locked
    and why a query-parameter secret key is a bad idea a merchant should not
    adopt (it lands in proxy logs). The ``Origin`` header *is* present on a
    socket handshake, so the origin lock still applies unchanged.

    Everything past this point is the same objects in the same order as REST.
    """
    runner, manifest = resolve_agent(websocket, agent_key)
    authenticated = await authenticate_request(websocket, token=token)
    if scopes:
        require_scopes(authenticated, *scopes)
    require_agent(authenticated, agent_key)
    return AgentContext(caller=authenticated, agent_key=agent_key, runner=runner, manifest=manifest)


@dataclass(frozen=True, slots=True)
class ConsoleActor:
    """A signed-in human, and the one merchant this request is about.

    Both halves are derived on the request. Neither is anything the browser
    said about itself.
    """

    user_id: str
    tenant_id: str


def console_user(request: Request) -> str:
    """Who is signed in, from the session cookie. 401 if nobody is.

    The cookie names a person and grants nothing else — no tenant, no role, no
    scopes (``neura_core.identity.session``). Everything a person may do is
    re-derived below, on every request, which is why revoking a membership bites
    immediately rather than at cookie expiry.
    """
    signed_in = verify_session(request.cookies.get(COOKIE_NAME, ""), get_settings().secret_key)
    if signed_in is None:
        raise AuthenticationError("Sign in to continue.")
    return signed_in.user_id


async def acting_for(request: Request, tenant_id: str) -> ConsoleActor:
    """Session → person → membership → tenant. `AGENTS.md` rule 3, in code.

    ``tenant_id`` arrives in the URL, and a URL is something the browser writes.
    That makes it a **suggestion**; :func:`~neura_core.identity.may_act_for` is
    what turns it into a decision, and it reads ``memberships`` fresh — the lock
    that already existed, with the doorman in front of it (ADR-0026).

    **404, not 403, for a tenant this person cannot act for.** The two are the
    same answer on purpose: a 403 would confirm that a tenant id exists, which
    turns this route into a way of asking whether a given merchant is a customer.
    The shadow grading endpoint already collapses the same pair for the same
    reason.
    """
    user_id = console_user(request)

    db = get_database()
    async with db.identity_session(user_id) as session:
        held = await memberships_for(session, user_id)

    if not any(membership.tenant_id == tenant_id for membership in held):
        log.info("console_tenant_refused", user_id=user_id)
        raise NotFoundError("No such shop.", details={"tenant_id": tenant_id})

    return ConsoleActor(user_id=user_id, tenant_id=tenant_id)


def database() -> Database:
    return get_database()


DatabaseDep = Annotated[Database, Depends(database)]


__all__ = [
    "AgentContext",
    "CallerDep",
    "ConsoleActor",
    "DatabaseDep",
    "acting_for",
    "agent_context",
    "authenticate_request",
    "bearer_token",
    "caller",
    "client_address",
    "console_user",
    "database",
    "require",
    "resolve_agent",
]
