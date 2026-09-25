"""SELL's own HTTP surface.

Mounted through the ``neura.agent_routes`` entry point at the manifest's
``route_prefix``, so ``neura-api`` never learns that an agent called "sell"
exists (ADR-0024 §8). Chat routes are generic and come from the API; a product
feed is not generic and no other agent has one.

Two very different kinds of endpoint live here, and the difference is the whole
of ADR-0024:

    GET  /feed/{token}/products.json     PUBLIC. No key. The token IS the access
    GET  /feed/{token}/products.jsonld   control, and it is in the URL.

    POST /mcp                            an external AI agent, `sell:mcp:connect`

    POST /suggestions                    a storefront page, `sell:suggest:read`

    POST   /feed                         merchant, `sell:feed:manage`
    GET    /feed                         merchant, `sell:feed:manage`
    POST   /feed/{id}/rotate             merchant, `sell:feed:manage`
    DELETE /feed/{id}                    merchant, `sell:feed:manage`

**The public routes are the only endpoints in this system with no
authentication.** Everything they touch is therefore reached through the token:
it names the tenant, the tenant scopes the session, and there is no request
parameter anywhere that widens either. A caller cannot ask for a different
store, a different tenant or a different entity type, because there is no
argument in which to say so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import APIRouter, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert, select, update
from sqlalchemy.engine import CursorResult

from neura_agent_sell import pairing as pairing_surface
from neura_agent_sell.feed import build, canonical, jsonld, publishable
from neura_agent_sell.feed import tokens as feed_tokens
from neura_agent_sell.feed.schema import sell_feeds
from neura_agent_sell.mcp import protocol as mcp_protocol
from neura_api.ratelimit import enforce, subjects_for
from neura_commerce.identity import EntityType
from neura_commerce.sync import DatabaseEntityStore
from neura_core import NotFoundError, get_logger
from neura_core.db import get_database
from neura_core.tenancy.schema import tenant_stores, tenants

log = get_logger(__name__)

#: Products per page. A crawler will happily ask for everything; a merchant with
#: 40,000 products would then have one request build a 40MB document and hold a
#: connection for the whole of it.
PAGE_SIZE = 500

#: How long a consumer may cache a document. The catalogue changes when a sync
#: runs, so anything shorter asks crawlers to refetch content that has not moved.
CACHE_SECONDS = 3600

_FEEDS = sell_feeds.c


class FeedCreated(BaseModel):
    """The one and only time the token exists outside the merchant's records."""

    model_config = ConfigDict(frozen=True)

    id: str
    store_id: str
    token_prefix: str
    #: **Shown once.** Stored hashed, so this cannot be produced again — see
    #: ADR-0024. The field name says so, because a merchant who saves the
    #: response body has saved everything they will ever get.
    url_shown_once: str
    formats: list[str] = Field(default_factory=list)


class SuggestionRequest(BaseModel):
    """What a storefront page sends.

    **`product_ids` is deliberately not called `cart_items`.** The name is the
    contract: this surface is told what is on a page, never what a shopper is
    doing, and a field called `cart` would make the second reading the natural
    one for whoever wires up the next platform.

    Over-long lists are truncated rather than refused (`select.MAX_INPUT_IDS`):
    a shopper with eleven things in their basket should not meet a validation
    error on the cart page.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_ids: list[str] = Field(default_factory=list, max_length=100)
    #: Optional while a tenant has one shop, which is the MVP shape
    #: (`StoreDirectory.connect`). Stated rather than implied, because
    #: `tenant_stores` already allows several.
    store_id: str | None = Field(default=None, max_length=128)


async def _managing_caller(request: Request, agent_key: str) -> Any:
    """Authenticate a merchant managing publication.

    Three checks, and one deliberate omission.

    Checked: the key is valid, it holds ``sell:feed:manage``, and the tenant has
    bought this agent. Not checked: whether the agent is **runnable**.

    That omission is the point. `agent_context` — what the chat routes use —
    resolves a runner and refuses with ``AGENT_NOT_RUNNABLE`` when there is no
    graph. A feed has no graph and never will; publishing a catalogue is not a
    conversation. Requiring a runner here would make the feed unreachable until
    the recommendation surface ships, which would be a graph the feed does not
    use gating a feature that does not need it.
    """
    from neura_api.dependencies import authenticate_request
    from neura_core.tenancy.auth import require_agent, require_scopes

    caller = await authenticate_request(request)
    require_scopes(caller, "sell:feed:manage")
    require_agent(caller, agent_key)
    return caller


def build_routes(agent_key: str) -> APIRouter:
    """SELL's routes. ``agent_key`` is passed for symmetry with the generic
    router and to keep the entry-point contract identical for agent #3."""
    router = APIRouter(tags=[agent_key])

    # ── Public ────────────────────────────────────────────────────────────────

    @router.get(
        "/feed/{token}/products.json",
        summary="A store's catalogue in the canonical model (public)",
        include_in_schema=False,
    )
    async def canonical_feed(
        request: Request,
        token: Annotated[str, Path()],
        after: Annotated[str | None, Query()] = None,
    ) -> Response:
        return await _serve(request, token, after=after, renderer=canonical)

    @router.get(
        "/feed/{token}/products.jsonld",
        summary="A store's catalogue as Schema.org Product (public)",
        include_in_schema=False,
    )
    async def jsonld_feed(
        request: Request,
        token: Annotated[str, Path()],
        after: Annotated[str | None, Query()] = None,
    ) -> Response:
        return await _serve(request, token, after=after, renderer=jsonld)

    # ── MCP ───────────────────────────────────────────────────────────────────

    @router.post("/mcp", summary="Model Context Protocol endpoint for external AI agents")
    async def mcp_endpoint(request: Request) -> Response:
        """One JSON-RPC message over Streamable HTTP.

        **Authenticated, unlike the feed.** The caller presents a key holding
        `sell:mcp:connect`, and that key is the only thing that decides which
        tenant's catalogue is reachable. There is no tenant, store or scope
        parameter anywhere in the protocol, so an external agent cannot ask
        about a catalogue other than the one their key names — the abuse is
        unexpressible rather than refused.

        **No runner is required**, for the same reason the feed needs none: MCP
        is not a conversation and has no graph.

        Plain JSON, not SSE. The spec permits either; a streaming response would
        mean holding a connection per external agent for calls that complete in
        one round trip, and nothing here streams.
        """
        import json

        caller = await _mcp_caller(request, agent_key)

        try:
            message = json.loads(await request.body())
        except ValueError:
            return _json(mcp_protocol.parse_error(), status=400)

        ctx = await _mcp_context(request, caller)
        try:
            response = await _mcp_server().handle(message, ctx)
        finally:
            # The adapter holds an HTTP client. One built per request and
            # abandoned leaks a connection pool per external agent, and an MCP
            # client polls.
            await _close(ctx.adapter)

        # A notification gets no body. 202 rather than 200 with an empty object:
        # the protocol says a notification has no response, and inventing one is
        # the violation a strict client rejects.
        if response is None:
            return Response(status_code=202)

        return _json(response)

    # ── Storefront ────────────────────────────────────────────────────────────

    @router.post("/suggestions", summary="Products that go with the ones a page names")
    async def suggestions(request: Request, body: SuggestionRequest) -> dict[str, Any]:
        """What goes with these products ([ADR-0040]).

        **The fourth surface, and the third with no model in it.** A page sends
        product ids; ordinary code reads the merchant's own product text, drops
        the anchor's own category and returns at most two products. Nothing is
        generated, so nothing here can fabricate a product or be
        prompt-injected.

        **We are never told these ids came from a cart, and must not be.** The
        Generic Commerce Interface has nine endpoints and none of them is a
        cart; every platform exposes one differently, so asking the shop about
        carts would mean per-platform code and would break
        [Rule 1](../../../../AGENTS.md). A page that knows what it is displaying
        already has the ids, which is why this needs no tenth endpoint.

        **No runner is required**, for the same reason the feed and MCP need
        none: a pairing is not a conversation and has no graph.

        **An empty result is a 200.** Unknown ids, a store that cannot search,
        a product with no categories, nothing complementary in the catalogue —
        all of them return `suggestions: []` and the block does not render.
        Showing nothing costs a shopper nothing; a 4xx on a cart page costs the
        merchant a support ticket about an error nobody can act on.
        """
        caller = await _suggest_caller(request, agent_key)
        await _suggest_rate_limit(request, caller)

        connection = await request.app.state.stores.connect(
            caller.tenant_id, store_id=body.store_id
        )
        try:
            pairing = await pairing_surface.suggest(
                body.product_ids,
                adapter=connection.adapter,
                capabilities=connection.capabilities,
                tenant_id=caller.tenant_id,
            )
        finally:
            # Same reason as MCP: the adapter holds an HTTP client, and a cart
            # page is loaded far more often than a conversation is started.
            await _close(connection.adapter)

        return {
            "heading": pairing.heading,
            "paired_with": pairing.paired_with,
            "suggestions": pairing.suggestions,
        }

    # ── Merchant ──────────────────────────────────────────────────────────────

    @router.post("/feed", summary="Start publishing a store's catalogue")
    async def create_feed(request: Request, store_id: Annotated[str, Query()]) -> dict[str, Any]:
        """Publication begins here, and only here.

        There is no `enabled` column to flip — a feed is the existence of a row
        (ADR-0024), so nothing can turn publication on for a merchant who did
        not ask, and no migration can turn it on for everyone at once.
        """
        caller = await _managing_caller(request, agent_key)
        issued = feed_tokens.generate()
        feed_id = f"feed_{uuid.uuid4().hex[:16]}"

        db = get_database()
        async with db.tenant_session(caller.tenant_id) as session:
            await session.execute(
                insert(sell_feeds).values(
                    id=feed_id,
                    tenant_id=caller.tenant_id,
                    store_id=store_id,
                    token_prefix=issued.token_prefix,
                    token_hash=issued.token_hash,
                )
            )

        log.info(
            "feed_published",
            tenant_id=caller.tenant_id,
            store_id=store_id,
            feed_id=feed_id,
            # The prefix, never the token. A URL in a log is a published
            # catalogue for anyone who reads logs.
            token_prefix=issued.token_prefix,
        )

        base = str(request.base_url).rstrip("/")
        return FeedCreated(
            id=feed_id,
            store_id=store_id,
            token_prefix=issued.token_prefix,
            url_shown_once=f"{base}/v1/sell/feed/{issued.token}/products.jsonld",
            formats=["products.jsonld", "products.json"],
        ).model_dump()

    @router.get("/feed", summary="This tenant's feeds — never their addresses")
    async def list_feeds(request: Request) -> dict[str, Any]:
        caller = await _managing_caller(request, agent_key)
        db = get_database()

        async with db.tenant_session(caller.tenant_id) as session:
            rows = (
                await session.execute(
                    select(
                        _FEEDS.id,
                        _FEEDS.store_id,
                        _FEEDS.token_prefix,
                        _FEEDS.created_at,
                        _FEEDS.rotated_at,
                        _FEEDS.last_served_at,
                    )
                    .where(_FEEDS.tenant_id == caller.tenant_id)
                    .order_by(_FEEDS.created_at.desc())
                )
            ).all()

        return {
            "data": [
                {
                    "id": row.id,
                    "store_id": row.store_id,
                    "token_prefix": row.token_prefix,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
                    "last_served_at": (
                        row.last_served_at.isoformat() if row.last_served_at else None
                    ),
                    "published": row.rotated_at is None,
                }
                for row in rows
            ]
        }

    @router.post("/feed/{feed_id}/rotate", summary="Replace a feed's address")
    async def rotate_feed(request: Request, feed_id: Annotated[str, Path()]) -> dict[str, Any]:
        """A new address; the old one stops resolving immediately.

        **This is not an undo.** It stops future fetches and does nothing about
        what has already been cached, indexed or republished elsewhere
        (ADR-0024). The response says so, because a merchant asking to rotate is
        usually asking to un-publish and those are different things.
        """
        caller = await _managing_caller(request, agent_key)
        db = get_database()
        issued = feed_tokens.generate()
        new_id = f"feed_{uuid.uuid4().hex[:16]}"

        async with db.tenant_session(caller.tenant_id) as session:
            row = (
                await session.execute(
                    select(_FEEDS.store_id).where(
                        _FEEDS.id == feed_id,
                        _FEEDS.tenant_id == caller.tenant_id,
                        _FEEDS.rotated_at.is_(None),
                    )
                )
            ).one_or_none()

            if row is None:
                raise NotFoundError(f"No published feed with id {feed_id!r}.")

            # The old row is marked, not deleted. "This feed was rotated on the
            # 3rd" answers a merchant asking why their submitted URL stopped
            # working; a deleted row answers nothing.
            await session.execute(
                update(sell_feeds)
                .where(_FEEDS.id == feed_id, _FEEDS.tenant_id == caller.tenant_id)
                .values(rotated_at=_now())
            )
            await session.execute(
                insert(sell_feeds).values(
                    id=new_id,
                    tenant_id=caller.tenant_id,
                    store_id=row.store_id,
                    token_prefix=issued.token_prefix,
                    token_hash=issued.token_hash,
                )
            )

        log.info("feed_rotated", tenant_id=caller.tenant_id, was=feed_id, now=new_id)

        base = str(request.base_url).rstrip("/")
        return {
            "id": new_id,
            "store_id": row.store_id,
            "token_prefix": issued.token_prefix,
            "url_shown_once": f"{base}/v1/sell/feed/{issued.token}/products.jsonld",
            "previous_id": feed_id,
            "note": (
                "The previous address stops resolving immediately. It does not "
                "recall anything already fetched, cached or republished."
            ),
        }

    @router.delete("/feed/{feed_id}", summary="Stop publishing")
    async def unpublish_feed(request: Request, feed_id: Annotated[str, Path()]) -> dict[str, Any]:
        caller = await _managing_caller(request, agent_key)
        db = get_database()

        async with db.tenant_session(caller.tenant_id) as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(sell_feeds)
                    .where(
                        _FEEDS.id == feed_id,
                        _FEEDS.tenant_id == caller.tenant_id,
                        _FEEDS.rotated_at.is_(None),
                    )
                    .values(rotated_at=_now())
                ),
            )
            # Zero rows means it did not exist, belonged to another tenant, or
            # was already unpublished. All three are the same 404: a caller
            # learns nothing about feeds that are not theirs.
            if result.rowcount == 0:
                raise NotFoundError(f"No published feed with id {feed_id!r}.")

        log.info("feed_unpublished", tenant_id=caller.tenant_id, feed_id=feed_id)
        return {
            "id": feed_id,
            "published": False,
            "note": (
                "The address stops resolving immediately. It does not recall "
                "anything already fetched, cached or republished."
            ),
        }

    return router


# ── MCP plumbing ─────────────────────────────────────────────────────────────

_MCP_SERVER: Any = None


def _mcp_server() -> Any:
    """One server per process.

    It compiles nothing and holds no per-caller state, but it does build a tool
    registry, and doing that per request would put registry construction inside
    an external agent's latency for no benefit.
    """
    global _MCP_SERVER
    if _MCP_SERVER is None:
        from neura_agent_sell.mcp import McpServer

        _MCP_SERVER = McpServer()
    return _MCP_SERVER


async def _mcp_caller(request: Request, agent_key: str) -> Any:
    """Authenticate an external AI agent.

    `sell:mcp:connect` and not `sell:chat:write`: an agent reading a catalogue
    and a shopper holding a conversation are different callers with different
    powers, and one scope for both would make the narrower one unexpressible.
    """
    from neura_api.dependencies import authenticate_request
    from neura_core.tenancy.auth import require_agent, require_scopes

    caller = await authenticate_request(request)
    require_scopes(caller, "sell:mcp:connect")
    require_agent(caller, agent_key)
    return caller


async def _suggest_caller(request: Request, agent_key: str) -> Any:
    """Authenticate a storefront page.

    `sell:suggest:read` and not `sell:catalogue:read`: the catalogue scope is
    held by keys that read products directly, and this one is served to every
    browser that loads a merchant's cart page. ADR-0040 §1 says the surface has
    "a different consumer, a different gate and a different failure mode" — the
    gate is this line, and a shared scope would make the narrower power
    unexpressible, exactly as `sell:mcp:connect` exists so an external agent
    cannot hold a conversation.

    **No runner is resolved**, as with the feed and MCP: there is no graph.
    """
    from neura_api.dependencies import authenticate_request
    from neura_core.tenancy.auth import require_agent, require_scopes

    caller = await authenticate_request(request)
    require_scopes(caller, "sell:suggest:read")
    require_agent(caller, agent_key)
    return caller


async def _suggest_rate_limit(request: Request, caller: Any) -> None:
    """ADR-0017's ladder, with no conversation to narrow it.

    A cart page loads for every visitor, so this is the busiest authenticated
    endpoint SELL has. `conversation_id=None` is honest rather than lazy —
    there is no conversation — which leaves the public-key case limited by
    tenant, key and client address.
    """
    from neura_api.dependencies import client_address

    enforce(
        await request.app.state.limiter.check(
            subjects_for(caller, client=client_address(request), conversation_id=None)
        )
    )


async def _mcp_context(request: Request, caller: Any) -> Any:
    """The security boundary's input — none of which the caller chooses.

    The tenant, the store, the capabilities and the scopes all come from the
    authenticated key. **`identity` is left at its anonymous default and that is
    deliberate**: an external AI agent has proven nothing about any shopper, so
    it must start having proven nothing. None of SELL's tools is
    session-scoped today, and if one ever is, this is the line that keeps it
    unreachable from here.
    """
    from neura_agent_core.tools import ToolContext

    connection = await request.app.state.stores.connect(caller.tenant_id)

    return ToolContext(
        tenant_id=caller.tenant_id,
        conversation_id=f"mcp_{uuid.uuid4().hex[:12]}",
        capabilities=connection.capabilities,
        scopes=caller.scopes,
        adapter=connection.adapter,
    )


async def _close(adapter: Any) -> None:
    closer = getattr(adapter, "aclose", None) or getattr(adapter, "close", None)
    if closer is None:
        return
    try:
        result = closer()
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:  # pragma: no cover — cleanup must never mask a reply
        log.warning("mcp_adapter_not_closed", error=str(exc))


def _json(body: dict[str, Any], *, status: int = 200) -> Response:
    import json

    return Response(
        content=json.dumps(body),
        media_type="application/json",
        status_code=status,
    )


# ── Serving a public document ────────────────────────────────────────────────


async def _serve(
    request: Request,
    token: str,
    *,
    after: str | None,
    renderer: Any,
) -> Response:
    """One public fetch, start to finish.

    **Every 404 in here is the same 404.** Malformed token, unknown token,
    rotated token, tenant that no longer exists — a caller learns only that
    there is nothing at this address. Distinguishing them would turn the
    endpoint into an oracle that confirms which tokens are real, which is the
    same reason `orders.py` uses one message for "no such order" and "not your
    order".
    """
    db = get_database()

    await _rate_limit(request, token)

    feed = await feed_tokens.resolve(db, token)
    if feed is None:
        raise NotFoundError("No feed at this address.")

    store = await _store_for(db, feed)
    if store is None:
        raise NotFoundError("No feed at this address.")

    entities = await DatabaseEntityStore(db, feed.tenant_id).page(
        feed.tenant_id,
        store.platform,
        EntityType.PRODUCT,
        limit=PAGE_SIZE,
        after=after,
    )

    document = build(
        # `True` here means "publish what the sync recorded", not "assert
        # everything is available". The honest work is done by the tri-state
        # already in the data: a store that declares no live inventory feed
        # synced `in_stock=None`, and `publishable()` carries that through to an
        # absent field rather than a guessed `InStock`.
        #
        # The staleness half of `sell.md §7.2` — withholding availability when
        # the last sync is too old — is **not implemented**, and is left visible
        # rather than faked. It needs a freshness bound, and `sell.md §12`
        # records that no such number has been measured. A bound invented here
        # would be a number chosen to fill a gap in a public document.
        publishable(list(entities.entities), may_assert_availability=True),  # type: ignore[arg-type]
        store_name=store.name,
        availability_asserted=True,
        next_cursor=_next_url(request, entities.next_after),
    )

    if feed_tokens.should_record_serve(feed):
        await feed_tokens.record_serve(db, feed)

    return _response(renderer.render(document), renderer.MEDIA_TYPE, document)


def _response(body: dict[str, Any], media_type: str, document: Any) -> Response:
    """The document, plus the HTTP a crawler actually reads.

    `Last-Modified` carries the **sync's** time, matching the body. A crawler
    that trusts the header and a consumer that trusts the body must not be able
    to disagree about how old a price is.
    """
    import json

    headers = {
        "Cache-Control": f"public, max-age={CACHE_SECONDS}",
        # Nothing here is per-caller, but a public URL that ends up behind a
        # shared cache should never have a response varied by a credential
        # header it does not read.
        "Vary": "Accept-Encoding",
        # A feed is a machine-readable copy of a storefront. It is not a page
        # anyone should be linking *from* us, and it must never be framed.
        "X-Robots-Tag": "noindex",
        "X-Content-Type-Options": "nosniff",
    }
    if document.synced_at:
        headers["Last-Modified"] = document.synced_at.strftime("%a, %d %b %Y %H:%M:%S GMT")

    return Response(
        content=json.dumps(body, separators=(",", ":")),
        media_type=media_type,
        headers=headers,
    )


async def _rate_limit(request: Request, token: str) -> None:
    """Limited by address and by feed, since there is no key to limit.

    ADR-0017's rule unchanged — several subjects, the narrowest binds. The feed
    subject is keyed on the token's *hash*, so a rate-limit bucket in Redis
    never contains a published URL.
    """
    from neura_api.dependencies import client_address
    from neura_api.ratelimit import Subject, enforce
    from neura_core import get_settings

    settings = get_settings()
    limiter = request.app.state.limiter

    enforce(
        await limiter.check(
            [
                Subject("client", client_address(request), settings.rate_limit_per_client),
                Subject(
                    "feed",
                    feed_tokens.fingerprint(token)[:32],
                    settings.rate_limit_per_key,
                ),
            ]
        )
    )


@dataclass(frozen=True, slots=True)
class _FeedStore:
    """The little a feed needs to know about a store."""

    store_id: str
    platform: str
    name: str | None


async def _store_for(db: Any, feed: feed_tokens.ResolvedFeed) -> _FeedStore | None:
    """The store this feed publishes — from our own tables, and nothing else.

    **This deliberately does not build an adapter.** `StoreDirectory.connect()`
    would give richer information, including live capability negotiation, and it
    reaches the merchant's own server to get it.

    That is exactly what must not happen here. This is the only unauthenticated
    endpoint in the system, so anything it triggers is something an anonymous
    caller can trigger — and "a crawler makes us call the merchant's shop" is a
    traffic amplifier pointed at the person paying us. The feed answers entirely
    from data we already hold, which is also why it stays fast enough to serve
    from cache.

    The tenant's own name is used as the store name: `tenant_stores` has no name
    column, and the merchant's name is the thing a consumer of a feed would
    recognise anyway.
    """
    async with db.tenant_session(feed.tenant_id) as session:
        row = (
            await session.execute(
                select(tenant_stores.c.id, tenant_stores.c.platform)
                .where(
                    tenant_stores.c.tenant_id == feed.tenant_id,
                    tenant_stores.c.id == feed.store_id,
                )
                .limit(1)
            )
        ).one_or_none()

        if row is None:
            # The feed outlived its store. Same 404 as an unknown token: a
            # caller learns there is nothing here, not why.
            return None

        name = await session.scalar(
            select(tenants.c.name).where(tenants.c.tenant_id == feed.tenant_id)
        )

    return _FeedStore(store_id=str(row.id), platform=str(row.platform), name=name)


def _next_url(request: Request, next_after: str | None) -> str | None:
    if next_after is None:
        return None
    return str(request.url.include_query_params(after=next_after))


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


__all__ = ["CACHE_SECONDS", "PAGE_SIZE", "FeedCreated", "SuggestionRequest", "build_routes"]
