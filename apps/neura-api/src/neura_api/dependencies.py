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
  ([ADR-0026](../../../../docs/architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) §3),
  then → role → permission (ADR-0058), declared on each route with
  :class:`Permitted`.

None of them is the security boundary. The policy engine authorises every tool
call again, in code, at the point of use. These exist so a caller gets a clean
refusal before any work happens — and so the refusal names something they can
act on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.routing import APIRoute, iter_route_contexts
from starlette.routing import BaseRoute
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
from neura_core.identity import COOKIE_NAME, is_permission, memberships_for, role_may
from neura_core.identity import verify as verify_session
from neura_core.identity.roles import ROLE_NOT_ALLOWED
from neura_core.identity.sign_up import SHOP_WAITING, WAITING_MESSAGE
from neura_core.tenancy import (
    CUSTOMER_SECRET_PREFIX,
    SHOP_TOKEN_PREFIX,
    ApiKeyKind,
    AuthenticatedCaller,
    TenantRepository,
    TenantStatus,
    authenticate,
    require_agent,
    require_scopes,
)
from neura_core.tenancy import keys as api_keys

log = get_logger(__name__)

BEARER = "bearer"

#: The refusal of a secret key sent from a web page (G55). Its own code, so the
#: chat box can say exactly what is wrong, and a test can name it. S105 reads it
#: as a password; it names a refusal, and no secret is near it.
SECRET_KEY_IN_PAGE = "SECRET_KEY_IN_PAGE"  # noqa: S105

#: The refusal of the shop token sent from a web page (G57). The shop token is
#: the bridge's password, never a key for NEURA, so it fails anyway; its own code
#: lets the chat box say that it is in the page, where anyone can copy it.
SHOP_TOKEN_IN_PAGE = "SHOP_TOKEN_IN_PAGE"  # noqa: S105

#: The refusal of the customer sign-in secret sent from a web page (ADR-0057 §3),
#: for the same reason: it signs customer passes on the shop's server.
CUSTOMER_SECRET_IN_PAGE = "CUSTOMER_SECRET_IN_PAGE"  # noqa: S105


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

    **Only a public key may travel in the address.** An address is written down
    by things we do not control — the web server's own request line, a proxy's
    access log, a browser's history — and the web server's line did print the
    whole key (CONNECTING_A_NEW_SHOP_LOG.md G34). A public key is public by
    design; a secret one in an address is a leak waiting for a log reader. A
    server is not a browser and *can* send a header, so a secret key over the
    socket goes in ``Authorization``, as on every REST route. Refused before any
    lookup, and without saying whether the key exists.

    **A secret key never comes from a web page** (G55). A browser marks every
    request a page makes with ``Origin``; a server's HTTP client does not. A
    secret key arriving with one has been put in a page, where anyone can read
    it. Without this rule it worked there, quietly: the chat box's socket refused
    it in the address, then its plain-request fallback sent it in the header,
    and a secret key is not tied to any address. Refused on its shape alone,
    before any lookup, so the page may read why (``SECRET_KEY_IN_PAGE``).

    **Nor does the shop token** (G57). It is the bridge's password (``fn_st_``),
    which NEURA sends to the shop and never accepts, so it would fail as an
    unknown key; but that refusal is unreadable, and the chat box could only say
    it could not reach the assistant while the token sat in the page. Refused on
    its shape too, readable, with its own code.
    """
    if token is not None:
        parsed = api_keys.parse(token)
        if parsed is not None and parsed[0] is not ApiKeyKind.PUBLIC:
            raise AuthenticationError(
                "A secret key may not be sent in the address. "
                "Send it in the Authorization header instead."
            )
    presented = token or bearer_token(request.headers.get("authorization"))
    origin = request.headers.get("origin")

    if origin and presented:
        _refuse_a_secret_in_a_page(request, presented)

    caller = await authenticate(
        get_database(),
        presented,
        # Only public keys are origin-locked, and only they consult this. A
        # missing Origin header on an `fn_pk_` request is a refusal, because an
        # empty allowlist permits nothing (ADR-0014 §3).
        origin=origin,
    )
    state = getattr(request, "state", None)
    if state is not None:
        state.caller = caller
    return caller


def _refuse_a_secret_in_a_page(request: Request | WebSocket, presented: str) -> None:
    """Refuse a secret key or the shop token that came from a web page.

    Decided from the string the page itself sent, before any lookup, so letting
    the page read the refusal tells it nothing new (middleware/cors.py).
    """
    parsed = api_keys.parse(presented)
    if parsed is not None and parsed[0] is ApiKeyKind.SECRET:
        refusal = AuthenticationError(
            "A secret key may not be used from a web page, where anyone can read it. "
            "Use the shop's public key (fn_pk_…) in the page, and keep secret keys "
            "on your server.",
            code=SECRET_KEY_IN_PAGE,
        )
    elif presented.strip().startswith(SHOP_TOKEN_PREFIX):
        refusal = AuthenticationError(
            "This is the shop token. It belongs in your bridge's settings, never in a "
            "web page, where anyone can read it. Use the shop's public key (fn_pk_…) "
            "in the page. If this page was public, ask the shop owner to make a new "
            "shop token.",
            code=SHOP_TOKEN_IN_PAGE,
        )
    elif presented.strip().startswith(CUSTOMER_SECRET_PREFIX):
        refusal = AuthenticationError(
            "This is the customer sign-in secret. It belongs on your shop's server, where it "
            "signs customer passes, never in a web page, where anyone can read it. Use the "
            "shop's public key (fn_pk_…) in the page. If this page was public, ask the shop "
            "owner to make a new customer sign-in secret.",
            code=CUSTOMER_SECRET_IN_PAGE,
        )
    else:
        return
    state = getattr(request, "state", None)
    if state is not None:
        state.secret_key_in_page = True
    raise refusal


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
    """A signed-in human, the one merchant this request is about, and their role there.

    All three are derived on the request. None is anything the browser said
    about itself.
    """

    user_id: str
    tenant_id: str
    role: str


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


async def acting_for(request: Request, tenant_id: str, *, permission: str) -> ConsoleActor:
    """Session → person → membership → tenant → role → permission. `AGENTS.md` rule 3, in code.

    ``tenant_id`` arrives in the URL, and a URL is something the browser writes.
    That makes it a **suggestion**; the membership, read fresh from
    ``memberships``, is what turns it into a decision — the lock that already
    existed, with the doorman in front of it (ADR-0026).

    **404, not 403, for a tenant this person cannot act for.** The two are the
    same answer on purpose: a 403 would confirm that a tenant id exists, which
    turns this route into a way of asking whether a given merchant is a customer.
    The shadow grading endpoint already collapses the same pair for the same
    reason.

    **403 for a member whose role does not include ``permission``** (ADR-0058
    §1): they already know the shop exists, and a plain refusal naming their
    role is easier to understand than a pretence that it does not. The role is
    read with the membership, on this request, so a changed role bites on the
    person's next click.

    **403 ``SHOP_WAITING`` for a shop waiting for approval** (ADR-0058 §7),
    whatever the role: a waiting shop opens nothing but the waiting screen,
    which reads only ``/me``. Read on every request, so approval opens the shop
    on the Owner's next click. A stranger still gets 404 first.

    ``permission`` has no default, so no caller can forget it. Routes state it
    with :class:`Permitted` rather than calling this, so it is checked before
    the body is read (G89) and a test can find it on the route.
    """
    user_id = console_user(request)

    db = get_database()
    async with db.identity_session(user_id) as session:
        held = await memberships_for(session, user_id)

    membership = next((m for m in held if m.tenant_id == tenant_id), None)
    if membership is None:
        log.info("console_tenant_refused", user_id=user_id)
        raise NotFoundError("No such shop.", details={"tenant_id": tenant_id})

    async with db.tenant_session(tenant_id) as session:
        shop = await TenantRepository(session).get(tenant_id)
    if shop is not None and shop.status is TenantStatus.WAITING:
        log.info("console_shop_waiting", user_id=user_id, tenant_id=tenant_id)
        raise ForbiddenError(WAITING_MESSAGE, code=SHOP_WAITING)

    if not role_may(membership.role, permission):
        log.info(
            "console_permission_refused",
            user_id=user_id,
            tenant_id=tenant_id,
            role=membership.role,
            permission=permission,
        )
        raise ForbiddenError(
            "Your role in this shop doesn't include this. If you need it, ask the shop's owner.",
            code=ROLE_NOT_ALLOWED,
            details={"role": membership.role, "permission": permission},
        )

    return ConsoleActor(user_id=user_id, tenant_id=tenant_id, role=membership.role)


@dataclass(frozen=True, slots=True)
class Permitted:
    """A dependency: a member of the shop in the URL whose role holds ``permission``.

        @router.get("/conversations")
        async def conversations(
            actor: Annotated[ConsoleActor, Depends(Permitted(CONVERSATIONS_READ))],
        ) -> ...

    Stated **on the route**, for the reason :func:`require` gives for key
    scopes: a central table of paths is a table that drifts from the routes it
    describes. ``tests/unit/test_console_roles.py`` walks every dashboard route
    and fails for one without it, so a forgotten permission is a failed test
    rather than a screen open to every member.

    A dependency runs before FastAPI reads the body and the query, so a stranger
    gets 404 and a member without the permission 403 whatever they sent (G89).
    """

    permission: str

    def __post_init__(self) -> None:
        # At import, when the route is declared: a misspelt permission would
        # otherwise refuse every request at run time, Owner included.
        if not is_permission(self.permission):
            raise ValueError(f"not a permission: {self.permission!r}")

    async def __call__(self, request: Request, tenant_id: str) -> ConsoleActor:
        return await acting_for(request, tenant_id, permission=self.permission)


def declared_permissions(routes: Sequence[BaseRoute]) -> frozenset[str]:
    """Every permission a route declares with :class:`Permitted`, an agent's included.

    Gathered once, after the agents are mounted, so ``/me`` can tell the
    dashboard which of them a person's role holds without the dashboard keeping
    its own copy of the map, and without this package naming any agent.
    """
    found: set[str] = set()
    for context in iter_route_contexts(routes):
        route = context.original_route
        if not isinstance(route, APIRoute):
            continue
        stack = list(route.dependant.dependencies)
        while stack:
            dependency = stack.pop()
            if isinstance(dependency.call, Permitted):
                found.add(dependency.call.permission)
            stack.extend(dependency.dependencies)
    return frozenset(found)


def database() -> Database:
    return get_database()


DatabaseDep = Annotated[Database, Depends(database)]


__all__ = [
    "ROLE_NOT_ALLOWED",
    "AgentContext",
    "CallerDep",
    "ConsoleActor",
    "DatabaseDep",
    "Permitted",
    "acting_for",
    "agent_context",
    "authenticate_request",
    "bearer_token",
    "caller",
    "client_address",
    "console_user",
    "database",
    "declared_permissions",
    "require",
    "resolve_agent",
]
