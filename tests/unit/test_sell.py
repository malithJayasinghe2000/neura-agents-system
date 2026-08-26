"""NEURA-SELL.

Built in the order `docs/agents/sell.md` recommends: the two surfaces with no
model in them first — the feed, then MCP — because both are deterministic, both
are testable without a model server, and neither costs a single inference.

**These are tests, not evals, and that distinction is open question E8.** The
feed is a pure function of synced entities: it cannot regress in the way an eval
exists to catch, and calling its checks "an eval" would inflate the suite with
cases that can only ever pass or fail deterministically. The conversational
surface, when it exists, is graded by `make eval` like CARE's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from neura_agent_sell import MANIFEST
from neura_agent_sell.feed import build, canonical, jsonld, publishable
from neura_agent_sell.mcp import McpServer
from neura_agent_sell.mcp.server import PROTOCOL_VERSION
from neura_agent_sell.tools import MCP_TOOLS, SELL_TOOLS, TOOL_SCOPES
from neura_domain import Capability, Money, Product, ProductStatus, ProductVariant


class TestManifest:
    """The identity card — what SELL needs, and what it may do."""

    def test_it_needs_both_halves_of_a_recommendation(self) -> None:
        """Search finds candidates; read expands them. Neither alone is enough.

        Required rather than optional so a merchant learns at *connection* time
        that this agent will not work for their store, instead of discovering it
        through a shopper being handed to a human.
        """
        assert MANIFEST.requires_capabilities == {
            Capability.PRODUCT_SEARCH,
            Capability.PRODUCT_READ,
        }

    def test_the_optional_capabilities_each_degrade_something_named(self) -> None:
        """Optional means the agent still runs, worse, in a way sell.md §3.3 names."""
        assert MANIFEST.optional_capabilities == {
            Capability.INVENTORY_READ,
            Capability.CATEGORY_READ,
        }

    def test_it_requires_no_capability_that_could_change_a_store(self) -> None:
        """The whole scope is read-only, on every surface (ADR-0010, ADR-0023).

        Asserted against the *enum* rather than against a list written here, so
        a capability added to `neura-domain` later is caught by this test rather
        than silently permitted by an allowlist nobody updated.
        """
        writes = {c for c in Capability if c.value.endswith(".write")}
        declared = MANIFEST.requires_capabilities | MANIFEST.optional_capabilities
        assert not (declared & writes)

    def test_the_feed_has_no_scope_because_it_has_no_key(self) -> None:
        """The point of ADR-0024, pinned.

        A crawler presents nothing, so there is no scope to check. What *is*
        scoped is switching publication on — a different and much sharper power,
        because it is close to irreversible.
        """
        assert "sell:feed:read" not in MANIFEST.scopes
        assert "sell:feed:manage" in MANIFEST.scopes

    def test_an_external_agents_key_cannot_hold_a_conversation(self) -> None:
        """`sell:mcp:connect` is deliberately not `sell:chat:write`.

        An external AI agent reading the catalogue and a shopper talking to
        SELL are different callers with different powers, and one scope for
        both would make the narrower one unexpressible.
        """
        assert {"sell:mcp:connect", "sell:chat:write"} <= MANIFEST.scopes
        assert "sell:mcp:connect" != "sell:chat:write"


class TestDiscovery:
    """How the deployable finds SELL — and what it correctly does not find yet."""

    def test_the_api_discovers_sell_without_naming_it(self) -> None:
        from neura_api.registry import discover_agents

        agents = discover_agents()
        assert "sell" in agents
        assert agents["sell"].route_prefix == "/v1/sell"

    def test_sell_is_runnable_now_that_a_graph_exists(self) -> None:
        """It deliberately was not, until there was something to run.

        A runner registered before the graph existed would have mounted
        `/v1/sell/chat` and answered every shopper with an exception — "we have
        it and it is broken" presented as though it were working. Until this
        commit the route answered `AGENT_NOT_RUNNABLE`, which was the true state.
        """
        from neura_api.registry import discover_runners

        assert "sell" in discover_runners()

    def test_sell_is_measured_by_the_eval_harness(self) -> None:
        """ "No agent ships without one" (AGENTS.md).

        Registered only now that there is behaviour to grade — a target wired
        earlier would have let `make eval` report a suite measuring nothing.
        """
        from importlib.metadata import entry_points

        assert "sell" in {ep.name for ep in entry_points(group="neura.eval_targets")}

    def test_sell_supplies_its_own_routes(self) -> None:
        """The feed and MCP, mounted without the API importing this package."""
        from neura_api.registry import discover_agent_routes

        assert "sell" in discover_agent_routes()


@pytest.mark.parametrize("forbidden", ["bagisto", "shopify", "woocommerce", "magento"])
def test_sell_names_no_commerce_platform(forbidden: str) -> None:
    """Rule 1, checked here too rather than trusted to the CI grep alone.

    The standalone script covers the whole tree; this fails inside the suite a
    developer actually runs, where the feedback is immediate.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "agents/sell/src"
    hits = [
        str(p.relative_to(src)) for p in src.rglob("*.py") if forbidden in p.read_text().lower()
    ]
    assert not hits, f"{forbidden!r} appears in {hits}"


# ── The feed ─────────────────────────────────────────────────────────────────
#
# Deterministic throughout. No model, no database, no clock.

SYNCED = datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
OLDER = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)


def _product(
    *,
    external_id: str = "p_1",
    title: str = "Waterproof Hiking Shoe",
    status: ProductStatus = ProductStatus.ACTIVE,
    variants: list[ProductVariant] | None = None,
    synced_at: datetime = SYNCED,
    **kwargs: object,
) -> Product:
    """A product as the sync engine would have stored it — provenance included."""
    return Product(
        neura_id="prd_internal_9f2",
        tenant_id="tn_secret",
        external_id=external_id,
        platform="acme-commerce",
        synced_at=synced_at,
        raw={"cost_price": "12.00", "supplier": "Northwind Ltd", "internal_flag": True},
        title=title,
        status=status,
        variants=variants if variants is not None else [],
        **kwargs,  # type: ignore[arg-type]
    )


def _variant(
    external_id: str = "v_1",
    *,
    price: str | None = "89.99",
    currency: str = "GBP",
    in_stock: bool | None = True,
    barcode: str | None = None,
    **kwargs: object,
) -> ProductVariant:
    return ProductVariant(
        external_id=external_id,
        price=Money(amount=Decimal(price), currency=currency) if price else None,
        in_stock=in_stock,
        barcode=barcode,
        **kwargs,  # type: ignore[arg-type]
    )


def _render_both(products: list[Product], *, availability: bool = True) -> str:
    """Every renderer's output, as one searchable string.

    The leak tests assert against *all* renderings at once on purpose. A test
    that checked only the one it was written for would pass while a second
    renderer published the same secret.
    """
    import json

    items = publishable(products, may_assert_availability=availability)
    doc = build(items, availability_asserted=availability)
    return json.dumps(canonical.render(doc)) + json.dumps(jsonld.render(doc))


class TestNothingInternalIsPublished:
    """The allowlist. If any of these fail, something private is public forever."""

    def test_the_platforms_raw_payload_never_reaches_a_document(self) -> None:
        """`raw` is unbounded and we do not know what is in it.

        The fixture puts a cost price and a supplier name in there, which is
        exactly the shape of thing a real platform includes and a merchant would
        never publish.
        """
        rendered = _render_both([_product()])
        assert "cost_price" not in rendered
        assert "Northwind" not in rendered
        assert "internal_flag" not in rendered

    def test_the_commerce_platform_is_not_named(self) -> None:
        """Free reconnaissance for anyone deciding what to attack."""
        assert "acme-commerce" not in _render_both([_product()])

    def test_our_internal_identifiers_are_not_published(self) -> None:
        """The merchant's id is published; ours are meaningless outside here."""
        rendered = _render_both([_product()])
        assert "tn_secret" not in rendered
        assert "prd_internal_9f2" not in rendered
        assert "p_1" in rendered

    def test_stock_quantity_has_no_field_to_leak_through(self) -> None:
        """Not dropped at render time — absent from the type entirely.

        A field that exists but is skipped is one careless edit from being
        emitted. `PublishableVariant` has nowhere to put it.

        Asserted on the parsed structure, not on a substring of the JSON: a
        quantity of 3 also appears inside a timestamp, and a check that matches
        that is a check that fails for the wrong reason.
        """
        from neura_agent_sell.feed.publishable import PublishableVariant

        assert "stock_quantity" not in PublishableVariant.model_fields

        items = publishable(
            [_product(variants=[_variant(stock_quantity=3)])], may_assert_availability=True
        )
        rendered = canonical.render(build(items))["products"][0]["variants"][0]
        assert not [k for k in rendered if "quantity" in k or "stock_q" in k]
        assert 3 not in rendered.values()

    def test_a_new_canonical_field_is_not_published_until_somebody_adds_it(self) -> None:
        """The reason the allowlist is a type rather than an `exclude=` argument.

        `PublishableProduct` must not simply mirror `Product`. If this ever
        fails, someone has made the projection inherit from the canonical model
        and a denylist has quietly replaced the allowlist.
        """
        from neura_agent_sell.feed.publishable import PublishableProduct

        assert not set(Product.model_fields) <= set(PublishableProduct.model_fields)
        for private in ("raw", "platform", "tenant_id", "neura_id"):
            assert private not in PublishableProduct.model_fields


class TestWhatMayBePublished:
    def test_only_active_products_are_published(self) -> None:
        """A higher bar than the agent applies in conversation, deliberately."""
        products = [
            _product(external_id="live", status=ProductStatus.ACTIVE),
            _product(external_id="wip", status=ProductStatus.DRAFT),
            _product(external_id="gone", status=ProductStatus.ARCHIVED),
            _product(external_id="dunno", status=ProductStatus.UNKNOWN),
        ]
        items = publishable(products, may_assert_availability=True)
        assert [p.product_id for p in items] == ["live"]

    def test_an_unmappable_status_is_withheld_rather_than_assumed_for_sale(self) -> None:
        """`UNKNOWN` means the adapter could not map it.

        Publishing on the strength of not knowing, into a document that is
        cached and cannot be recalled, asserts something nobody established.
        """
        assert (
            publishable([_product(status=ProductStatus.UNKNOWN)], may_assert_availability=True)
            == []
        )


class TestAvailabilityIsNeverGuessed:
    def test_availability_is_omitted_when_it_cannot_be_asserted(self) -> None:
        """No live inventory feed, or a stale sync. Absent, never `OutOfStock`.

        On the parsed documents rather than on their text. `availability` is a
        substring of `availability_asserted`, which is a legitimate and
        deliberately different field — a naive `not in` here fails a correct
        document, which is worse than no check because it trains a reader to
        ignore the case.
        """
        items = publishable(
            [_product(variants=[_variant(in_stock=True)])], may_assert_availability=False
        )
        doc = build(items, availability_asserted=False)

        variant = canonical.render(doc)["products"][0]["variants"][0]
        assert "in_stock" not in variant

        offer = jsonld.render(doc)["itemListElement"][0]["item"]["offers"]
        assert "availability" not in offer

    def test_out_of_stock_is_stated_when_it_is_known(self) -> None:
        """ "We do not know" and "we do not have it" are different claims."""
        items = publishable(
            [_product(variants=[_variant(in_stock=False)])], may_assert_availability=True
        )
        offers = jsonld.render(build(items))["itemListElement"][0]["item"]["offers"]
        assert offers["availability"] == jsonld.OUT_OF_STOCK

    def test_an_empty_catalogue_is_not_read_as_a_store_with_no_inventory_feed(self) -> None:
        """`availability_asserted` is stated rather than inferred from the items."""
        doc = build([], availability_asserted=True)
        assert canonical.render(doc)["availability_asserted"] is True


class TestTheTimestampIsTheSyncs:
    def test_it_is_derived_from_the_data_not_from_a_clock(self) -> None:
        """Serve-time cannot leak in, because there is nowhere to pass it."""
        items = publishable(
            [_product(external_id="a", synced_at=OLDER), _product(external_id="b")],
            may_assert_availability=True,
        )
        doc = build(items)
        assert doc.synced_at == SYNCED
        assert canonical.render(doc)["synced_at"] == SYNCED.isoformat()
        assert jsonld.render(doc)["dateModified"] == SYNCED.isoformat()

    def test_build_accepts_no_timestamp_argument_at_all(self) -> None:
        """The structural half of the rule. A comment would not have held."""
        import inspect

        from neura_agent_sell.feed.document import build as build_fn

        params = set(inspect.signature(build_fn).parameters)
        assert not params & {"generated_at", "synced_at", "now", "timestamp"}

    def test_an_empty_document_claims_no_date(self) -> None:
        assert canonical.render(build([]))["synced_at"] is None
        assert "dateModified" not in jsonld.render(build([]))


class TestPricesSurviveTheRoundTrip:
    def test_money_is_a_string_never_a_json_number(self) -> None:
        """A consumer parsing `1099.90` as a float has already lost the price."""
        items = publishable(
            [_product(variants=[_variant(price="1099.90")])], may_assert_availability=True
        )
        offer = jsonld.render(build(items))["itemListElement"][0]["item"]["offers"]
        assert offer["price"] == "1099.90"
        assert isinstance(offer["price"], str)
        variant = canonical.render(build(items))["products"][0]["variants"][0]
        assert variant["price"] == "1099.90"

    def test_a_trailing_zero_is_not_lost(self) -> None:
        """`Decimal("18.00")` is a price; `18.0` is a rounding of one."""
        items = publishable(
            [_product(variants=[_variant(price="18.00")])], may_assert_availability=True
        )
        assert canonical.render(build(items))["products"][0]["variants"][0]["price"] == "18.00"


class TestSchemaOrgMapping:
    def test_one_offer_per_priced_variant(self) -> None:
        """The shape that answers "have you got it in a UK 9, and how much"."""
        items = publishable(
            [
                _product(
                    variants=[
                        _variant("v_8", price="89.99", options={"size": "UK 8"}),
                        _variant("v_9", price="94.99", options={"size": "UK 9"}),
                    ]
                )
            ],
            may_assert_availability=True,
        )
        offers = jsonld.render(build(items))["itemListElement"][0]["item"]["offers"]
        assert [o["price"] for o in offers] == ["89.99", "94.99"]

    def test_mixed_currencies_never_collapse_into_one_aggregate_offer(self) -> None:
        """An `AggregateOffer` carries a single `priceCurrency`.

        Emitting one for a product priced in two currencies would pick a
        currency on the merchant's behalf. A list of offers cannot be wrong
        about it.
        """
        items = publishable(
            [
                _product(
                    variants=[
                        _variant("v_gbp", price="89.99", currency="GBP"),
                        _variant("v_eur", price="99.99", currency="EUR"),
                    ]
                )
            ],
            may_assert_availability=True,
        )
        offers = jsonld.render(build(items))["itemListElement"][0]["item"]["offers"]
        assert {o["priceCurrency"] for o in offers} == {"GBP", "EUR"}
        assert all(o["@type"] == "Offer" for o in offers)

    def test_a_product_level_price_range_becomes_an_aggregate_offer(self) -> None:
        """Some platforms carry price at product level only.

        Without this the item is published with no price and is useless to every
        consumer that reads the document.
        """
        items = publishable(
            [
                _product(
                    price_range_min=Money(amount=Decimal("18.00"), currency="GBP"),
                    price_range_max=Money(amount=Decimal("24.00"), currency="GBP"),
                )
            ],
            may_assert_availability=True,
        )
        offer = jsonld.render(build(items))["itemListElement"][0]["item"]["offers"]
        assert offer["@type"] == "AggregateOffer"
        assert (offer["lowPrice"], offer["highPrice"]) == ("18.00", "24.00")

    def test_no_ratings_are_ever_synthesised(self) -> None:
        """We hold no review data. Inventing one is the thing GUARD detects."""
        assert "aggregateRating" not in _render_both([_product()])
        assert "review" not in _render_both([_product()]).lower()

    def test_a_barcode_is_published_only_when_it_is_really_a_gtin(self) -> None:
        """A malformed `gtin` gets the item rejected, not merely ignored.

        The merchant is then absent from the channel they paid for, with
        nothing saying why.
        """
        good = publishable(
            [_product(variants=[_variant(barcode="5012345678900")])],
            may_assert_availability=True,
        )
        assert good[0].variants[0].gtin == "5012345678900"

        for junk in ("SHELF-42", "978-0-13-235088-4-X", "12345"):
            items = publishable(
                [_product(variants=[_variant(barcode=junk)])], may_assert_availability=True
            )
            assert items[0].variants[0].gtin is None, junk

    def test_the_document_is_valid_json_ld_with_one_root_context(self) -> None:
        items = publishable([_product()], may_assert_availability=True)
        body = jsonld.render(build(items, store_name="Acme Outdoors"))
        assert body["@context"] == "https://schema.org"
        assert body["@type"] == "ItemList"
        assert body["name"] == "Acme Outdoors"
        assert body["itemListElement"][0]["position"] == 1
        assert body["itemListElement"][0]["item"]["@type"] == "Product"


# ── Tools ────────────────────────────────────────────────────────────────────


class TestToolsCannotChangeAStore:
    def test_every_tool_is_read_only(self) -> None:
        """ADR-0010, asserted rather than asserted-in-a-docstring.

        A checkout tool is not disabled or hidden here — it does not exist, so
        the most persuasive injection imaginable has nothing to invoke.
        """
        from neura_domain import SideEffect

        assert {spec.side_effect for spec in SELL_TOOLS} == {SideEffect.READ}

    def test_the_registry_refuses_a_write_tool(self) -> None:
        """The structural half. The list above is what we wrote; this is what
        the engine would accept if somebody wrote something else."""
        from neura_agent_core.tools import ToolRegistrationError, ToolRegistry, tool
        from neura_domain import SideEffect

        @tool(
            name="place_order",
            description="Buy it.",
            side_effect=SideEffect.WRITE,
            scopes=["sell:catalogue:read"],
        )
        async def place_order(product_ref: str, ctx: object) -> str: ...  # pragma: no cover

        with pytest.raises(ToolRegistrationError):
            ToolRegistry([place_order])

    def test_no_tool_declares_pii_output(self) -> None:
        """A catalogue is public, and SELL never reads a customer record.

        Over-declaring is its own bug: it would evict a public search from the
        semantic cache for nothing and make the flag meaningless where it
        matters, which is CARE's order tools.
        """
        assert not [spec.name for spec in SELL_TOOLS if spec.pii_output]

    def test_the_manifest_declares_every_scope_the_tools_require(self) -> None:
        """Otherwise a correctly-provisioned key is refused at the policy
        engine's third check while looking perfectly configured — a failure that
        reads as "the agent never calls any tool"."""
        assert MANIFEST.scopes >= TOOL_SCOPES

    def test_escalate_is_available_on_every_store(self) -> None:
        """The only action the agent can always take, by design."""
        from neura_agent_sell.tools import escalate_to_human

        assert escalate_to_human.requires == frozenset()


class TestWhatAnExternalAgentMayReach:
    def test_mcp_is_an_allowlist_not_a_subtraction(self) -> None:
        """The default for a new tool is private.

        If this were `SELL_TOOLS - {escalate}`, adding a tool would expose it to
        third parties the moment it was written, and nobody would notice until
        it was already public.
        """
        assert {spec.name for spec in SELL_TOOLS} > MCP_TOOLS
        assert "escalate_to_human" not in MCP_TOOLS

    def test_no_exposed_tool_can_write(self) -> None:
        from neura_domain import SideEffect

        exposed = [spec for spec in SELL_TOOLS if spec.name in MCP_TOOLS]
        assert exposed
        assert {spec.side_effect for spec in exposed} == {SideEffect.READ}

    def test_no_exposed_tool_reads_a_person(self) -> None:
        """An external AI agent must not be a route to a merchant's customers.

        Asserted against capabilities rather than a list of tool names, so a
        future tool that requires `CUSTOMER_READ` or `ORDER_READ` fails here
        rather than shipping quietly.
        """
        from neura_domain import Capability

        personal = {Capability.CUSTOMER_READ, Capability.ORDER_READ, Capability.ORDER_SEARCH}
        for spec in SELL_TOOLS:
            if spec.name in MCP_TOOLS:
                assert not (spec.requires & personal), spec.name


# ── MCP ──────────────────────────────────────────────────────────────────────


def _ctx(capabilities: frozenset[Capability] | None = None, **kwargs: object) -> Any:
    from neura_agent_core.tools import ToolContext

    return ToolContext(
        tenant_id="tn_mcp",
        conversation_id="mcp_test",
        capabilities=(
            capabilities
            if capabilities is not None
            else frozenset(
                {
                    Capability.PRODUCT_SEARCH,
                    Capability.PRODUCT_READ,
                    Capability.INVENTORY_READ,
                    Capability.CATEGORY_READ,
                }
            )
        ),
        scopes=frozenset(TOOL_SCOPES),
        **kwargs,  # type: ignore[arg-type]
    )


class TestMcpProtocol:
    async def test_a_notification_gets_no_response(self) -> None:
        """Answering one is a violation a lenient client tolerates and a strict
        one rejects — the worst kind, because it works in testing."""
        server = McpServer()
        assert await server.handle({"jsonrpc": "2.0", "method": "ping"}, _ctx()) is None

    async def test_a_wrong_jsonrpc_version_is_an_invalid_request(self) -> None:
        server = McpServer()
        out = await server.handle({"jsonrpc": "1.0", "id": 1, "method": "ping"}, _ctx())
        assert out is not None
        assert out["error"]["code"] == -32600

    async def test_an_unknown_method_uses_the_standard_code(self) -> None:
        """Not our own number. A client's error handling is written against the
        JSON-RPC table, and a bespoke code arrives as "unknown error"."""
        server = McpServer()
        out = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "wat"}, _ctx())
        assert out is not None
        assert out["error"]["code"] == -32601

    async def test_initialize_serves_the_pinned_revision_not_the_requested_one(self) -> None:
        """Echoing a client's version claims conformance we have not tested."""
        server = McpServer()
        out = await server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "1999-01-01"},
            },
            _ctx(),
        )
        assert out is not None
        assert out["result"]["protocolVersion"] == PROTOCOL_VERSION

    async def test_no_capability_is_advertised_that_is_not_implemented(self) -> None:
        """A capability advertised and unimplemented is worse than one absent,
        because a client will try it. Notably: no `sampling`, which would put
        someone else's model in our request path with no eval and no verify."""
        server = McpServer()
        out = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, _ctx())
        assert out is not None
        assert set(out["result"]["capabilities"]) == {"tools"}


class TestMcpExposure:
    async def test_it_lists_only_tools_the_store_can_satisfy(self) -> None:
        """A store with no live inventory feed never learns `check_stock` exists.

        Stronger than refusing the call: you cannot talk a model into invoking a
        tool it was never shown.
        """
        server = McpServer()
        out = await server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            _ctx(frozenset({Capability.PRODUCT_SEARCH, Capability.PRODUCT_READ})),
        )
        assert out is not None
        names = {t["name"] for t in out["result"]["tools"]}
        assert names == {"search_products", "get_product_details"}

    async def test_escalate_is_never_listed(self) -> None:
        """No human in an MCP session to escalate to, and a tool that files into
        a merchant's support queue on a bot's say-so is a DoS with a nice name."""
        server = McpServer()
        out = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _ctx())
        assert out is not None
        assert "escalate_to_human" not in {t["name"] for t in out["result"]["tools"]}

    async def test_calling_an_unexposed_tool_reports_unknown_not_refused(self) -> None:
        """ "Not available here" and "you may not" tell a caller different
        things, and only the first is true."""
        server = McpServer()
        out = await server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "escalate_to_human", "arguments": {"reason": "x"}},
            },
            _ctx(),
        )
        assert out is not None
        assert out["error"]["code"] == -32602
        assert "Unknown tool" in out["error"]["message"]

    async def test_a_tool_the_store_cannot_satisfy_cannot_be_called(self) -> None:
        """Listed or not, the policy engine is the boundary."""
        server = McpServer()
        out = await server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "check_stock", "arguments": {"variant_refs": ["v1"]}},
            },
            _ctx(frozenset({Capability.PRODUCT_SEARCH, Capability.PRODUCT_READ})),
        )
        assert out is not None
        assert "error" in out or out["result"]["isError"] is True

    async def test_the_protocol_carries_no_way_to_name_another_tenant(self) -> None:
        """The isolation argument for this surface, stated as a property.

        Every method takes its tenant from the resolved `ToolContext`. If a
        parameter ever appeared that could name a tenant, store or scope, an
        external agent could ask about a catalogue their key does not cover.
        """
        import inspect

        source = inspect.getsource(McpServer)
        for forbidden in ('params.get("tenant', 'params.get("store', 'params.get("scope'):
            assert forbidden not in source


# ── The graph ────────────────────────────────────────────────────────────────


def _invocation(tool: str, value: str, *, ok: bool = True) -> Any:
    from neura_agent_core.tools import ToolInvocation

    return ToolInvocation(
        tool_name=tool,
        ok=ok,
        value=value if ok else None,
        error=None if ok else "the store did not answer",
        latency_ms=1,
    )


def _runtime() -> Any:
    """A real `Runtime`, with no model and no store.

    `runtime_of` requires the genuine type, and rightly — a duck-typed stand-in
    would let a node be tested against a shape the graph never actually passes.
    Nothing here calls a model: these are the deterministic nodes.
    """
    from neura_agent_sell.runtime import build_runtime

    return build_runtime(
        tenant_id="tn_test",
        conversation_id="cnv_test",
        adapter=None,
        llm=None,
        capabilities=frozenset(),
        scopes=frozenset(),
    )


def _config() -> dict[str, Any]:
    from neura_agent_core.graph import CONFIG_KEY

    return {"configurable": {CONFIG_KEY: _runtime()}}


SEARCH_RESULT = """Product p_jacket_1: Fell Waterproof Jacket
  price: 149.00 GBP
  availability: in stock
  description: A 2.5-layer waterproof shell with taped seams.

Product p_jacket_3: Summit Expedition Hardshell
  price: 220.00 GBP
  availability: in stock
  description: A 3-layer expedition hardshell."""


class TestTheGraphShape:
    def test_it_compiles_with_every_node_the_design_names(self) -> None:
        from neura_agent_sell import compile_graph

        nodes = set(compile_graph().get_graph().nodes)
        assert {
            "guard",
            "route",
            "retrieve",
            "plan",
            "act",
            "shortlist",
            "compose",
            "verify",
            "respond",
            "decline",
            "no_match",
            "escalate",
            "blocked",
        } <= nodes

    def test_guard_runs_before_anything_reads_the_message(self) -> None:
        """A guard reached after routing has already shown the raw message to a
        model, so its redaction is redaction of something already disclosed —
        and it looks exactly like a guard that works.

        Asserted on the compiled graph's own first edge rather than by
        constructing a violation: the builder's contract check is
        `neura-agent-core`'s to test, and what SELL owes is that its graph
        satisfies it.
        """
        from neura_agent_sell import compile_graph

        edges = compile_graph().get_graph().edges
        first = {e.target for e in edges if e.source == "__start__"}
        assert first == {"guard"}


class TestShortlistDecidesWhatMayBeRecommended:
    """The node with no CARE counterpart, and the one carrying the product."""

    async def test_a_price_ceiling_is_enforced_in_code_not_in_prose(self) -> None:
        """ "Under 150" is the one thing a shopper will check.

        A model that includes a 220.00 jacket because it is otherwise perfect
        has produced the most embarrassing possible answer, so the filter runs
        before the composer sees anything.
        """
        from neura_agent_sell.nodes import shortlist

        out = await shortlist(
            {
                "invocations": [_invocation("search_products", SEARCH_RESULT)],
                "entities": {"max_price": "150"},
            },
            {},
        )
        assert out["promises"] == ["p_jacket_1"]
        assert "220.00" not in out["context"]

    async def test_a_rejected_candidate_never_reaches_the_composer(self) -> None:
        """A model shown eleven products and told to use four will use five."""
        from neura_agent_sell.nodes import shortlist

        out = await shortlist(
            {
                "invocations": [_invocation("search_products", SEARCH_RESULT)],
                "entities": {"max_price": "150"},
            },
            {},
        )
        assert "Summit" not in out["context"]

    async def test_an_unparsable_ceiling_does_not_empty_the_shortlist(self) -> None:
        """A bad extraction must not turn into "we sell nothing"."""
        from neura_agent_sell.nodes import shortlist

        out = await shortlist(
            {
                "invocations": [_invocation("search_products", SEARCH_RESULT)],
                "entities": {"max_price": "about a hundred quid"},
            },
            {},
        )
        assert len(out["promises"]) == 2


class TestWeDoNotSellThatIsAClaimAboutTheWholeStore:
    """The rule the whole design rests on, tested from both directions."""

    async def test_an_unanswered_catalogue_escalates_rather_than_denying(self) -> None:
        """A cold index or a timed-out adapter is NOT an empty catalogue.

        Collapsing the two tells a shopper that a fully stocked store is bare.
        """
        from neura_agent_sell.nodes import shortlist

        out = await shortlist(
            {"invocations": [_invocation("search_products", "", ok=False)], "entities": {}},
            {},
        )
        assert out["escalated"] is True
        assert "unknown" in out["escalation_reason"]

    async def test_no_tool_ran_at_all_escalates(self) -> None:
        from neura_agent_sell.nodes import shortlist

        out = await shortlist({"invocations": [], "entities": {}}, {})
        assert out["escalated"] is True

    async def test_a_searched_catalogue_that_returned_nothing_is_an_honest_miss(self) -> None:
        """The store WAS asked and DID answer. Now "we don't carry it" is true."""
        from neura_agent_sell.nodes import shortlist

        out = await shortlist(
            {
                "invocations": [
                    _invocation("search_products", "The catalogue returned no available products.")
                ],
                "entities": {},
            },
            {},
        )
        assert out["promises"] == []
        assert "escalated" not in out

    def test_the_branch_cannot_reach_no_match_without_the_evidence(self) -> None:
        """Belt and braces, and they fail for different reasons.

        The node already refuses to leave `escalated` unset when the catalogue
        was not reached, so this is redundant today. It is the line that keeps
        the claim true if someone later adds a path into the branch that skips
        the node's reasoning.
        """
        from neura_agent_sell.graph import _after_shortlist

        assert _after_shortlist({"promises": [], "invocations": []}) == "escalate"
        assert (
            _after_shortlist(
                {"promises": [], "invocations": [_invocation("search_products", "none")]}
            )
            == "no_match"
        )
        assert _after_shortlist({"promises": ["p_1"], "invocations": []}) == "compose"

    def test_an_escalated_turn_cannot_fall_through_to_no_match(self) -> None:
        """Ordering in the branch is load-bearing."""
        from neura_agent_sell.graph import _after_shortlist

        assert (
            _after_shortlist(
                {
                    "escalated": True,
                    "promises": [],
                    "invocations": [_invocation("search_products", "x")],
                }
            )
            == "escalate"
        )


class TestAFabricatedProductCannotReachAShopper:
    """Set membership, not a model grading a model. Gated at 1.00."""

    async def test_a_draft_naming_a_product_that_was_not_shortlisted_escalates(self) -> None:
        from neura_agent_sell.nodes import respond

        out = await respond(
            {
                "grounded": True,
                "draft": "I'd suggest the Summit Expedition Hardshell (p_jacket_3).",
                "promises": ["p_jacket_1"],
                "invocations": [_invocation("search_products", SEARCH_RESULT)],
            },
            _config(),
        )
        assert out["escalated"] is True
        assert "p_jacket_3" in out["escalation_reason"]

    def test_ordinary_prose_is_not_mistaken_for_a_citation(self) -> None:
        """The check is deliberately narrow.

        Only ids the store actually returned this turn are considered. A word
        that resembles an id but appeared in no tool result is prose, and
        flagging it would make the gate fire on correct replies.
        """
        from neura_agent_sell.nodes.respond import _invented_ids

        state = {
            "promises": ["p_jacket_1"],
            "invocations": [_invocation("search_products", SEARCH_RESULT)],
        }
        assert _invented_ids("The Fell jacket is waterproof and packs away.", state) == set()
        assert _invented_ids("Try p_jacket_3 instead.", state) == {"p_jacket_3"}


class TestTheTerminalNodesGenerateNothing:
    """`decline` and `no_match` skip `verify`, so nothing in them may be composed."""

    async def test_no_match_says_only_what_a_human_wrote_and_the_store_said(self) -> None:
        from neura_agent_sell.nodes import no_match

        out = await no_match(
            {
                "invocations": [
                    _invocation("list_categories", "This store's categories: Footwear, Outerwear")
                ]
            },
            _config(),
        )
        assert out["grounded"] is True
        assert out["refused"] is True
        assert out["escalated"] is False
        assert "Footwear, Outerwear" in out["reply"]

    async def test_no_match_stands_alone_when_the_store_publishes_no_categories(self) -> None:
        """`CATEGORY_READ` is optional, and this is the degradation sell.md names."""
        from neura_agent_sell.nodes import no_match
        from neura_agent_sell.prompts import load_prompts

        out = await no_match({"invocations": []}, _config())
        assert out["reply"] == load_prompts()["no_match"]


class TestPrompts:
    def test_every_prompt_the_graph_asks_for_exists(self) -> None:
        from neura_agent_sell.prompts import REQUIRED, load_prompts

        assert load_prompts().keys() >= REQUIRED

    def test_an_inherited_node_can_still_need_an_agent_supplied_prompt(self) -> None:
        """`verify` is inherited; its prompt is not, and leaving it out was a bug.

        The first SELL eval run escalated every answerable case with
        "verification could not be completed: KeyError". The graph was right and
        the node was right — SELL had simply never been given the words. It
        presents as the agent being cautious rather than as anything being
        broken, because `verify` fails closed exactly as designed, so nothing
        looked alarming until the gate was read.

        Pinned by importing the node's own constant: a future agent copying
        SELL's prompt list must not inherit the same omission.
        """
        from neura_agent_core.graph.nodes.verify import PROMPT_NAME
        from neura_agent_sell.prompts import load_prompts

        assert PROMPT_NAME in load_prompts()

    def test_the_revision_changes_when_a_prompt_changes(self) -> None:
        """Six weeks after a complaint, "which prompt wrote this?" needs an
        exact answer."""
        from neura_agent_sell.prompts import REVISION, prompt_hashes

        assert len(REVISION) == 64
        assert len(prompt_hashes()) >= 5
