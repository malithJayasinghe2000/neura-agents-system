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

import importlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from neura_agent_sell import MANIFEST
from neura_agent_sell import evidence as evidence_module
from neura_agent_sell.citations import cited_ids, without_ids
from neura_agent_sell.evals.store import load_store
from neura_agent_sell.evidence import WITHHELD, hide_uncited_descriptions
from neura_agent_sell.feed import build, canonical, jsonld, publishable
from neura_agent_sell.mcp import McpServer
from neura_agent_sell.mcp.server import PROTOCOL_VERSION
from neura_agent_sell.tools import MCP_TOOLS, SELL_TOOLS, TOOL_SCOPES, render
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

    def test_sell_supplies_its_own_background_work(self) -> None:
        """The fifth seam ([ADR-0045]): a pairing is computed on ADR-0022's
        queue, and `_job_runner` registers the handler without naming SELL.

        Keyed by **job kind**, because that is what `JobRunner.register`
        dispatches on — and `discover_job_handlers` refuses a kind claimed
        twice, since which handler ran would otherwise depend on entry-point
        iteration order.
        """
        from neura_agent_sell.pairing.cache import PAIRING_COMPUTE
        from neura_api.registry import discover_job_handlers

        handlers = discover_job_handlers(db=None, stores=None, llm=None)
        assert PAIRING_COMPUTE in handlers

    def test_a_handler_factory_that_raises_does_not_stop_the_worker(self) -> None:
        """One agent's background work must not deny the loop to every other
        agent — the same forgiveness a broken runner and a broken router get,
        and for the same reason."""
        from neura_api.registry import discover_job_handlers

        # `build_handlers` takes what it needs by keyword and ignores the rest.
        # Calling it with nothing at all is the closest thing to a broken
        # deployment this can reach without monkeypatching entry points.
        assert isinstance(discover_job_handlers(), dict)


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


def _routing_config(routed: Any) -> dict[str, Any]:
    """A runtime whose router returns exactly this `Route`.

    A real `ChatResponse`, not a duck-typed stand-in: `route` meters what it
    spends, and a fake that omits the cost is a fake of the wrong thing.
    """
    from neura_agent_core.graph import CONFIG_KEY
    from neura_agent_sell.runtime import build_runtime
    from neura_llm import ChatResponse

    class _Router:
        async def chat_structured(self, role: Any, request: Any, schema: type) -> Any:
            class Result:
                value = routed
                response = ChatResponse(content="", model="stub", provider="stub")

            return Result()

    return {
        "configurable": {
            CONFIG_KEY: build_runtime(
                tenant_id="tn_test",
                conversation_id="cnv_test",
                adapter=None,
                llm=_Router(),
                capabilities=frozenset(),
                scopes=frozenset(),
            )
        }
    }


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

    def test_a_rejected_short_id_is_still_caught(self) -> None:
        """G36: the check was blind to ids under three characters."""
        from neura_agent_sell.nodes.respond import _invented_ids

        result = "Product 4: Enamel Camp Mug 350ml\n\nProduct 5: Collapsible Silicone Cup"
        state = {
            "promises": ["4"],
            "invocations": [_invocation("search_products", result)],
        }
        assert _invented_ids("The mug (Product 4) is the one.", state) == set()
        assert _invented_ids("Or the cup (Product 5).", state) == {"5"}


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


class TestTheIndexMayNameACandidateNeverDescribeOne:
    """[ADR-0029], closes A16. Measured on the real shop: `trousers` returns 4
    and `jackets` returns 0, because the titles read "Waxed Cotton Field Jacket"
    and the merchant's search is a literal text match. One letter, and a shopper
    is told a shop with four jackets is empty — while `retrieve` had already
    found one in the same turn."""

    @staticmethod
    def _ctx_with(index_hits: list[str], store: dict[str, Any]) -> Any:
        from types import SimpleNamespace

        from neura_commerce import EntityType

        class _Retriever:
            async def search(self, query: str, **kw: Any) -> Any:
                chunks = [
                    SimpleNamespace(source_id=i, source_type=EntityType.PRODUCT, chunk_index=0)
                    for i in index_hits
                ]
                return SimpleNamespace(chunks=chunks)

        class _Adapter:
            def __init__(self) -> None:
                self.asked: list[str] = []

            async def search_products(self, query: Any) -> Any:
                return SimpleNamespace(items=[])

            async def get_product(self, ref: str) -> Any:
                self.asked.append(ref)
                return store.get(ref)

        adapter = _Adapter()
        return _ctx(adapter=adapter, retriever=_Retriever()), adapter

    async def test_the_index_rescues_a_search_the_store_could_not_match(self) -> None:
        from neura_agent_sell.tools.catalogue import search_products

        ctx, adapter = self._ctx_with(
            ["1311"], {"1311": _product(external_id="1311", title="Waxed Cotton Field Jacket")}
        )
        out = await search_products.fn("jackets", ctx)

        assert "Waxed Cotton Field Jacket" in out
        assert adapter.asked == ["1311"], "every fact must come from the live store"

    async def test_the_fallback_says_it_happened(self) -> None:
        """Stated, not silent — the cost this decision was weighed against is an
        unattributable recommendation months from now."""
        from neura_agent_sell.tools.catalogue import search_products

        ctx, _ = self._ctx_with(
            ["1311"], {"1311": _product(external_id="1311", title="Field Jacket")}
        )
        out = await search_products.fn("jackets", ctx)

        assert "store's own search returned nothing" in out
        assert "confirmed live" in out

    async def test_a_product_gone_since_the_sync_does_not_survive(self) -> None:
        """The freshness guarantee, kept. A stale index costs a wasted lookup,
        never a wrong claim in front of a shopper."""
        from neura_agent_sell.tools.catalogue import search_products

        ctx, adapter = self._ctx_with(["1311"], {})  # the store no longer has it
        out = await search_products.fn("jackets", ctx)

        assert adapter.asked == ["1311"]
        assert "no available products matching" in out
        assert "1311" not in out

    async def test_a_withdrawn_product_does_not_survive_either(self) -> None:
        from neura_agent_sell.tools.catalogue import search_products
        from neura_domain import ProductStatus

        ctx, _ = self._ctx_with(
            ["1311"],
            {
                "1311": _product(
                    external_id="1311", title="Field Jacket", status=ProductStatus.ARCHIVED
                )
            },
        )
        out = await search_products.fn("jackets", ctx)

        assert "no available products matching" in out

    async def test_no_index_behaves_exactly_as_before(self) -> None:
        """A tenant with no index, or one under a different embedding model,
        must be unchanged."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                return SimpleNamespace(items=[])

        out = await search_products.fn("jackets", _ctx(adapter=_Adapter()))
        assert "no available products matching" in out

    async def test_a_successful_store_search_never_reaches_the_index(self) -> None:
        """The fallback is for *nothing*, not for *not enough*. Merging the two
        would be a relevance judgement made in code with no data behind it."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        called = []

        class _Retriever:
            async def search(self, query: str, **kw: Any) -> Any:
                called.append(query)
                return SimpleNamespace(chunks=[])

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                return SimpleNamespace(
                    items=[_product(external_id="1305", title="Linen Drawstring Trousers")]
                )

            async def get_product(self, ref: str) -> Any:
                raise AssertionError("must not be called on a successful search")

        out = await search_products.fn("trousers", _ctx(adapter=_Adapter(), retriever=_Retriever()))
        assert "Linen Drawstring Trousers" in out
        assert called == [], "the index must not be consulted when the store answered"


class TestAProductCardIsDataTheWidgetDraws:
    """[ADR-0030]. The model names the products, the server states the facts,
    the widget draws the card — and no layer does another's job."""

    def test_a_card_carries_the_fields_a_shopper_needs(self) -> None:
        from neura_agent_sell.tools.card import product_card

        card = product_card(
            _product(
                external_id="1311",
                title="Waxed Cotton Field Jacket",
                url="https://shop.example/waxed-cotton-field-jacket",
                image_urls=["https://shop.example/img/1311.jpg"],
                variants=[_variant(external_id="1311", in_stock=True)],
            )
        )
        assert card is not None
        assert card["id"] == "1311"
        assert card["title"] == "Waxed Cotton Field Jacket"
        assert card["url"] == "https://shop.example/waxed-cotton-field-jacket"
        assert card["image"] == "https://shop.example/img/1311.jpg"
        assert card["in_stock"] == "true"

    def test_an_executable_url_is_dropped_not_rendered(self) -> None:
        """The only place merchant data becomes something a browser resolves."""
        from neura_agent_sell.tools.card import product_card

        card = product_card(
            _product(
                external_id="x",
                title="Trap",
                url="javascript:alert(1)",
                image_urls=["data:text/html,<script>alert(1)</script>"],
            )
        )
        assert card is not None
        assert "url" not in card, "a card renders without a link rather than with a trap"
        assert "image" not in card

    def test_a_relative_url_is_dropped(self) -> None:
        """No host, so nothing to trust. A card without an image is fine."""
        from neura_agent_sell.tools.card import product_card

        card = product_card(_product(external_id="x", title="T", url="/products/x"))
        assert card is not None
        assert "url" not in card

    def test_a_product_with_no_title_gets_no_card(self) -> None:
        from neura_agent_sell.tools.card import product_card

        assert product_card(_product(external_id="x", title="")) is None

    def test_a_withdrawn_product_is_marked_out_of_stock(self) -> None:
        """The same call `render.py` makes for the model. A card saying "In
        stock" beside prose saying otherwise is worse than either alone."""
        from neura_agent_sell.tools.card import product_card
        from neura_domain import ProductStatus

        card = product_card(_product(external_id="x", title="Gone", status=ProductStatus.ARCHIVED))
        assert card is not None
        assert card["in_stock"] == "false"


class TestCardsObeyTheFabricationCheck:
    """Cards need no safety argument of their own: they are built after the
    check that already gates every product id in a reply, and from the same
    set."""

    @staticmethod
    def _runtime_with(cards: dict[str, dict[str, str]]) -> Any:
        from neura_agent_core.graph import CONFIG_KEY
        from neura_agent_sell.runtime import build_runtime

        runtime = build_runtime(
            tenant_id="tn_test",
            conversation_id="cnv_test",
            adapter=None,
            llm=None,
            capabilities=frozenset(),
            scopes=frozenset(),
        )
        runtime.cards.update(cards)
        return {"configurable": {CONFIG_KEY: runtime}}

    async def test_only_products_the_reply_names_get_a_card(self) -> None:
        """A shortlist of four the composer wrote about twice produces two
        cards. Showing the others would be recommending products the reply did
        not choose, with pictures."""
        from neura_agent_sell.nodes import respond

        out = await respond(
            {
                "draft": "The 1311 and the 1315 are both good.",
                "grounded": True,
                "promises": ["1311", "1313", "1315", "1323"],
                "invocations": [
                    _invocation("search_products", "Product 1311: A\n\nProduct 1315: B")
                ],
            },
            self._runtime_with(
                {
                    "1311": {"id": "1311", "title": "A"},
                    "1313": {"id": "1313", "title": "B"},
                    "1315": {"id": "1315", "title": "C"},
                }
            ),
        )
        assert [c["id"] for c in out["cards"]] == ["1311", "1315"]

    async def test_cards_follow_the_order_the_reply_names_them(self) -> None:
        from neura_agent_sell.nodes import respond

        out = await respond(
            {
                "draft": "Start with 1315, or consider 1311.",
                "grounded": True,
                "promises": ["1311", "1315"],
                "invocations": [
                    _invocation("search_products", "Product 1311: A\n\nProduct 1315: B")
                ],
            },
            self._runtime_with(
                {"1311": {"id": "1311", "title": "A"}, "1315": {"id": "1315", "title": "B"}}
            ),
        )
        assert [c["id"] for c in out["cards"]] == ["1315", "1311"]

    async def test_the_shopper_reads_no_id_but_still_gets_the_card(self) -> None:
        """G41: the id comes out of the reply; the check and the card still used it."""
        from neura_agent_sell.nodes import respond

        out = await respond(
            {
                "draft": "I recommend the Ceylon Black Tea BOPF 400g (Product 4).",
                "grounded": True,
                "promises": ["4"],
                "invocations": [_invocation("search_products", "Product 4: Ceylon Black Tea")],
            },
            self._runtime_with({"4": {"id": "4", "title": "Ceylon Black Tea"}}),
        )
        assert out["reply"] == "I recommend the Ceylon Black Tea BOPF 400g."
        assert [c["id"] for c in out["cards"]] == ["4"]

    async def test_an_escalated_turn_carries_no_cards(self) -> None:
        """`respond` never runs, so there is nothing to show — which is how a
        withheld or blocked turn ends up with no products, by construction."""
        from neura_agent_sell.nodes import respond

        out = await respond(
            {"draft": "", "grounded": False, "promises": ["1311"]},
            self._runtime_with({"1311": {"id": "1311", "title": "A"}}),
        )
        assert out.get("escalated") is True
        assert "cards" not in out


class TestTheFallbackNeedsAWordInCommon:
    """[ADR-0029] amended. The index always returns its nearest neighbours, and
    "nearest" in a 29-product catalogue is not "relevant": measured on the real
    shop, `fishing rods` returns a **jacket** at 0.528 against a best of 0.545 —
    noise that looks exactly like signal."""

    async def test_noise_does_not_become_a_recommendation(self) -> None:
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products
        from neura_commerce import EntityType

        class _Retriever:
            async def search(self, query: str, **kw: Any) -> Any:
                return SimpleNamespace(
                    chunks=[
                        SimpleNamespace(
                            source_id="1304", source_type=EntityType.PRODUCT, chunk_index=0
                        )
                    ]
                )

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                return SimpleNamespace(items=[])

            async def get_product(self, ref: str) -> Any:
                return _product(external_id="1304", title="Halden Cargo Trousers")

        out = await search_products.fn(
            "fishing rods", _ctx(adapter=_Adapter(), retriever=_Retriever())
        )
        assert "no available products matching" in out
        assert "Halden" not in out, "trousers must not be offered for a fishing rod"

    def test_the_gate_is_the_merchants_words_not_a_score(self) -> None:
        """A threshold would need a number, and the scales are not comparable
        across embedding models — measured, `nomic-embed-text` runs 0.50 to 0.75
        on the same shop where `gemini-embedding-001` runs 0.53 to 0.66. Any
        constant would be right for one and wrong for the next."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import _shares_a_word

        jackets = [
            SimpleNamespace(title="Waxed Cotton Field Jacket", description="sheds rain"),
            SimpleNamespace(title="Lightweight Rain Shell", description="2.5-layer waterproof"),
        ]
        assert _shares_a_word("jackets", jackets) is True
        assert _shares_a_word("do you sell jackets?", jackets) is True
        assert _shares_a_word("fishing rods", jackets) is False

    def test_a_plural_is_what_this_exists_for(self) -> None:
        """`jackets` failing to match "Waxed Cotton Field Jacket" is the entire
        reason ADR-0029 exists; the gate must not undo it."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import _shares_a_word

        one = [SimpleNamespace(title="Waxed Cotton Field Jacket", description="")]
        assert _shares_a_word("jackets", one) is True
        assert _shares_a_word("jacket", one) is True

    def test_a_word_only_in_the_description_counts(self) -> None:
        """The Rain Shell is a jacket and never says so in its title."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import _shares_a_word

        shell = [SimpleNamespace(title="Lightweight Rain Shell", description="a packable jacket")]
        assert _shares_a_word("jackets", shell) is True

    def test_a_query_of_only_filler_words_never_opens_the_gate(self) -> None:
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import _shares_a_word

        anything = [SimpleNamespace(title="Waxed Cotton Field Jacket", description="rain")]
        assert _shares_a_word("do you have something", anything) is False


class TestTheHandoverSaysWhichFailureHappened:
    """Finding 7 in the testing log. `plan` chose `list_categories`, the store
    answered it in 202ms with six categories, and the handover said *"the
    catalogue could not be searched"* — so a support person reads an outage
    where there was none."""

    def test_no_lookup_at_all_says_so(self) -> None:
        from neura_agent_sell.nodes.shortlist import _no_evidence_reason

        assert "no catalogue lookup ran at all" in _no_evidence_reason([])

    def test_a_lookup_that_returns_no_products_does_not_read_as_an_outage(self) -> None:
        from neura_agent_sell.nodes.shortlist import _no_evidence_reason

        reason = _no_evidence_reason(["list_categories"])
        assert "the store answered" in reason
        assert "list_categories" in reason
        assert "could not be searched" not in reason

    async def test_a_category_list_still_escalates(self) -> None:
        """The escalation is not the bug and is not being relaxed. Categories
        are coarse: no "Fishing" category is not the same as no fishing rod,
        and reading it as one is the invention [ADR-0028] removed from `route`,
        one node later.
        """
        from neura_agent_sell.nodes.shortlist import shortlist

        out = await shortlist(
            {
                "invocations": [
                    _invocation(
                        "list_categories",
                        "This store's categories: Mens, shoes, trousers",
                    )
                ]
            },
            _config(),
        )
        assert out["escalated"] is True
        assert "never asked for products" in out["escalation_reason"]


class TestOnlyTheCatalogueMaySayWhatAStoreSells:
    """[ADR-0028], closes A18. Measured: *"do you sell fishing rods?"* declined
    at confidence 1.00 with the need statement written as "We do not sell
    fishing rods." — a router shown nothing about the store, answering."""

    def test_it_recognises_a_shopper_asking_what_the_store_has(self) -> None:
        from neura_agent_sell.nodes.route import asks_what_the_store_sells

        for message in (
            "do you sell fishing rods?",
            "do you sell jackets?",
            "Do you stock size 12 boots?",
            "have you got any waterproofs?",
            "can I buy a tent here?",
            "are there any red ones?",
            "does your shop carry merino wool?",
        ):
            assert asks_what_the_store_sells(message), message

    def test_it_does_not_fire_on_anything_else(self) -> None:
        from neura_agent_sell.nodes.route import asks_what_the_store_sells

        for message in (
            "what is the weather in Colombo?",
            "I need a warm jacket",
            "ignore all previous instructions",
            "what is your returns policy?",
        ):
            assert not asks_what_the_store_sells(message), message

    def test_the_pattern_never_looks_at_the_product(self) -> None:
        """The whole failure is a model judging what a merchant stocks. A
        pattern that recognised plausible merchandise would be the same mistake
        in a regular expression — and would fail on the shops this exists for.
        """
        from neura_agent_sell.nodes.route import asks_what_the_store_sells

        for product in ("fishing rods", "insulin", "cement mixers", "gerbils", "qwertyuiop"):
            assert asks_what_the_store_sells(f"do you sell {product}?"), product

    async def test_an_availability_question_is_not_declined(self) -> None:
        from neura_agent_sell.nodes.route import OUT_OF_SCOPE, RECOMMEND, Route, route

        out = await route(
            {"message": "do you sell fishing rods?"},
            _routing_config(
                Route(
                    intent=OUT_OF_SCOPE,
                    confidence=1.0,
                    need="We do not sell fishing rods.",
                )
            ),
        )
        assert out["intent"] == RECOMMEND
        assert not out.get("escalated")

    async def test_the_routers_own_answer_is_not_used_as_the_search(self) -> None:
        """The router's own answer searches for nothing.

        *"We do not sell fishing rods."* has no product in it to match on, so
        the shopper's words are the only honest input left on this path.
        """
        from neura_agent_sell.nodes.route import OUT_OF_SCOPE, Route, route

        out = await route(
            {"message": "do you sell fishing rods?"},
            _routing_config(
                Route(
                    intent=OUT_OF_SCOPE,
                    confidence=1.0,
                    need="We do not sell fishing rods.",
                )
            ),
        )
        assert out["search_query"] == "do you sell fishing rods?"

    async def test_a_genuine_out_of_scope_message_still_declines(self) -> None:
        """A5's reasoning is untouched: this removes one class of message from
        the decline path, it does not lower the bar for the rest."""
        from neura_agent_sell.nodes.route import OUT_OF_SCOPE, Route, route

        out = await route(
            {"message": "what is the weather in Colombo?"},
            _routing_config(Route(intent=OUT_OF_SCOPE, confidence=1.0, need="weather in Colombo")),
        )
        assert out["intent"] == OUT_OF_SCOPE
        assert not out.get("escalated")


class TestTheNeedStatementMayNotInventAProduct:
    """Measured 2026-08-27: *"do you sell jackets?"* produced the need statement
    "waterproof hiking jacket" — the model copied the illustration out of its
    own prompt. That sentence is what searches the catalogue, so a store hanging
    four plain jackets looks empty to a shopper who asked for what it stocks."""

    def test_an_invented_attribute_falls_back_to_the_shoppers_words(self) -> None:
        from neura_agent_sell.nodes.route import _grounded_need

        assert (
            _grounded_need("waterproof hiking jacket", "do you sell jackets?", [])
            == "do you sell jackets?"
        )

    def test_a_faithful_restatement_is_kept(self) -> None:
        from neura_agent_sell.nodes.route import _grounded_need

        assert _grounded_need("jackets", "do you sell jackets?", []) == "jackets"
        assert (
            _grounded_need("trousers under 40", "I need trousers under 40", [])
            == "trousers under 40"
        )

    def test_a_plural_is_not_an_invention(self) -> None:
        """The check must not fire on almost every turn — a false alarm is a
        quiet downgrade to the raw message."""
        from neura_agent_sell.nodes.route import _grounded_need

        assert _grounded_need("jacket", "do you sell jackets?", []) == "jacket"
        assert _grounded_need("jackets", "do you sell a jacket?", []) == "jackets"

    def test_a_pronoun_resolved_from_history_is_kept(self) -> None:
        """The whole reason the field exists (CARE's 1.9 measurement). Words
        from a turn the router was shown are the shopper's words too."""
        from neura_agent_sell.nodes.route import _grounded_need

        history = [{"role": "shopper", "content": "show me wool socks"}]
        assert (
            _grounded_need("wool socks in grey", "do you have those in grey?", history)
            == "wool socks in grey"
        )

    def test_the_same_rewrite_without_the_history_is_an_invention(self) -> None:
        """Same sentence, no source for it. The check is about provenance, not
        about the words themselves."""
        from neura_agent_sell.nodes.route import _grounded_need

        assert (
            _grounded_need("wool socks in grey", "do you have those in grey?", [])
            == "do you have those in grey?"
        )

    def test_an_empty_rewrite_still_falls_back_to_the_message(self) -> None:
        """Pre-existing behaviour, kept: an empty rewrite must not silently
        disable retrieval for the turn."""
        from neura_agent_sell.nodes.route import _grounded_need

        assert _grounded_need("   ", "do you sell jackets?", []) == "do you sell jackets?"

    def test_the_prompt_no_longer_shows_a_copyable_product(self) -> None:
        """The illustration was the cause. A test rather than a comment, because
        the next person to edit this file will not have read the log."""
        from neura_agent_sell.prompts import load_prompts

        assert "waterproof hiking jacket in blue" not in load_prompts()["route"]


class TestAConstraintMissIsNotAnEmptyStore:
    """[ADR-0027]. A15: one bad query must not speak for a merchant's catalogue."""

    def test_a_price_ceiling_is_stripped_from_the_search_text(self) -> None:
        """Measured on the test shop: `trousers` returns 4, `trousers under 40`
        returns 0. The ceiling is enforced by `shortlist`, in code, so the
        phrase was never filtering — only preventing a match."""
        from neura_agent_sell.tools.catalogue import strip_price_constraint

        assert strip_price_constraint("trousers under 40") == "trousers"
        assert strip_price_constraint("waterproof jacket below £150") == "waterproof jacket"
        assert strip_price_constraint("shoes less than $99.50") == "shoes"
        assert strip_price_constraint("a coat up to 200 dollars") == "a coat"

    def test_a_bare_number_is_not_a_price(self) -> None:
        """A stripper that ate these would trade one silent failure for another."""
        from neura_agent_sell.tools.catalogue import strip_price_constraint

        for query in ("size 40 trousers", "40 denier tights", "SPF 40 sunscreen"):
            assert strip_price_constraint(query) == query

    def test_a_query_that_is_only_a_budget_survives_intact(self) -> None:
        """An empty search is worse than a bad one."""
        from neura_agent_sell.tools.catalogue import strip_price_constraint

        assert strip_price_constraint("under 40") == "under 40"

    async def test_the_budget_case_says_what_was_found_and_what_it_cost(self) -> None:
        """The commonest real miss, and until ADR-0027 it was computed and
        thrown away — routed to the same sentence as an empty catalogue."""
        from neura_agent_sell.nodes import no_match

        out = await no_match(
            {
                "invocations": [],
                "miss": {
                    "kind": "constraint",
                    "found": "4",
                    "ceiling": "40.00",
                    "cheapest": "44.00",
                    "currency": "USD",
                },
            },
            _config(),
        )
        assert "I found 4" in out["reply"]
        assert "none under 40.00 USD" in out["reply"]
        assert "closest is 44.00 USD" in out["reply"]
        assert out["grounded"] is True
        assert out["refused"] is True

    async def test_the_budget_message_names_no_product(self) -> None:
        """ADR-0027 narrowed the prohibition on describing what was found; it
        did not lift the one on identifying it. A number cannot be added to a
        basket."""
        from neura_agent_sell.nodes import no_match

        out = await no_match(
            {
                "invocations": [
                    _invocation(
                        "search_products",
                        "Product 1305: Linen Drawstring Trousers\n  price: 44.00 USD",
                    )
                ],
                "miss": {
                    "kind": "constraint",
                    "found": "1",
                    "ceiling": "40.00",
                    "cheapest": "44.00",
                    "currency": "USD",
                },
            },
            _config(),
        )
        assert "Linen Drawstring" not in out["reply"]
        assert "1305" not in out["reply"]

    async def test_no_reply_claims_the_shop_does_not_carry_it(self) -> None:
        """The A15 sentence itself. One query a keyword engine could not match
        is not evidence that the shelf is bare."""
        from neura_agent_sell.nodes import no_match

        for miss in ({"kind": "empty"}, {"kind": "constraint", "found": "4", "ceiling": "40.00"}):
            out = await no_match({"invocations": [], "miss": miss}, _config())
            assert "doesn't appear to carry" not in out["reply"]
            assert "does not carry" not in out["reply"]

    async def test_an_unset_miss_falls_back_to_the_fixed_file(self) -> None:
        """A node that forgets to set `miss` must degrade to the old message,
        never to half a sentence."""
        from neura_agent_sell.nodes import no_match
        from neura_agent_sell.prompts import load_prompts

        out = await no_match({"invocations": []}, _config())
        assert out["reply"] == load_prompts()["no_match"]

    async def test_the_stripped_query_is_what_reaches_the_store(self) -> None:
        """The stripper is unit-tested above; this proves it is **wired**.

        Worth its own test because it could not be verified from a live run:
        three hand-run turns in the testing log all reached an answer without
        `search_products` being chosen at all, so no transcript showed what the
        merchant's search engine actually received.
        """
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        seen: list[str] = []

        class _RecordingAdapter:
            async def search_products(self, query: Any) -> Any:
                seen.append(query.text)
                return SimpleNamespace(items=[])

        await search_products.fn("trousers under 40", _ctx(adapter=_RecordingAdapter()))

        assert seen == ["trousers"], "the store must not be sent the price phrase"

    async def test_the_store_still_receives_a_query_with_no_price_in_it(self) -> None:
        """The common case must be untouched — stripping is not rewriting."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        seen: list[str] = []

        class _RecordingAdapter:
            async def search_products(self, query: Any) -> Any:
                seen.append(query.text)
                return SimpleNamespace(items=[])

        await search_products.fn("waterproof hiking jacket", _ctx(adapter=_RecordingAdapter()))

        # **The FIRST query is what this test is about**, and it is unchanged:
        # stripping is not rewriting. It asserted the whole list until
        # 2026-09-19, which was stricter than its own name — a phrase that finds
        # nothing is now searched again one term at a time (`_broadened`, A27),
        # so more queries legitimately follow. Those are covered below.
        assert seen[0] == "waterproof hiking jacket"


class TestAPhraseThatFindsNothingIsSearchedOneTermAtATime:
    """`_broadened` — open question A27, measured 2026-09-19.

    The merchant's search is an AND over terms: on the test shop
    `waterproof jacket` returns 0 while `waterproof` returns 2 and `jacket`
    returns 4, and SELL answered "I can't find anything" three turns running
    against a catalogue holding exactly what was asked for.
    """

    async def test_it_does_not_fire_when_the_phrase_found_something(self) -> None:
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        seen: list[str] = []

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                seen.append(query.text)
                return SimpleNamespace(items=[_product(external_id="1315")])

        await search_products.fn("waterproof jacket", _ctx(adapter=_Adapter()))

        assert seen == ["waterproof jacket"], "a successful search must not be retried"

    async def test_a_single_term_query_is_not_broadened(self) -> None:
        """There is nothing to broaden, and a second identical call is waste."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        seen: list[str] = []

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                seen.append(query.text)
                return SimpleNamespace(items=[])

        await search_products.fn("jacket", _ctx(adapter=_Adapter()))

        assert seen == ["jacket"]

    async def test_the_longest_term_is_tried_first(self) -> None:
        """**The ordering is the safety property.** Trying `jacket` first fills
        the shortlist with four jackets of which one is waterproof — the exact
        shape A22 fabricates from. `waterproof` first fills it with products
        that actually have the attribute."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        seen: list[str] = []

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                seen.append(query.text)
                return SimpleNamespace(items=[])

        await search_products.fn("waterproof jacket", _ctx(adapter=_Adapter()))

        assert seen == ["waterproof jacket", "waterproof", "jacket"]

    async def test_it_stops_at_the_first_term_that_finds_anything(self) -> None:
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        seen: list[str] = []

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                seen.append(query.text)
                hit = query.text == "waterproof"
                return SimpleNamespace(items=[_product(external_id="1315")] if hit else [])

        out = await search_products.fn("waterproof jacket", _ctx(adapter=_Adapter()))

        assert seen == ["waterproof jacket", "waterproof"], "it must not keep searching"
        assert "1315" in out

    async def test_the_reply_says_the_products_matched_only_one_word(self) -> None:
        """**The banner is a safety property, not decoration.** This text becomes
        evidence the composer writes from and `verify` checks against; without it
        a recovered shortlist reads exactly like one that satisfied the whole
        request."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                hit = query.text == "waterproof"
                return SimpleNamespace(items=[_product(external_id="1315")] if hit else [])

        out = await search_products.fn("waterproof jacket", _ctx(adapter=_Adapter()))

        assert "ONLY THAT ONE WORD" in out
        assert "'waterproof'" in out and "'waterproof jacket'" in out

    async def test_a_withdrawn_product_is_still_not_recommended(self) -> None:
        """Broadening must not become a way past the sellable filter."""
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                hit = query.text == "waterproof"
                return SimpleNamespace(
                    items=[_product(external_id="1315", status=ProductStatus.ARCHIVED)]
                    if hit
                    else []
                )

        out = await search_products.fn("waterproof jacket", _ctx(adapter=_Adapter()))

        assert "1315" not in out
        assert "no available products" in out

    async def test_it_spends_at_most_three_extra_searches(self) -> None:
        from types import SimpleNamespace

        from neura_agent_sell.tools.catalogue import search_products

        seen: list[str] = []

        class _Adapter:
            async def search_products(self, query: Any) -> Any:
                seen.append(query.text)
                return SimpleNamespace(items=[])

        await search_products.fn(
            "lightweight waterproof breathable hooded jacket", _ctx(adapter=_Adapter())
        )

        assert len(seen) == 4, "the original, plus at most MAX_BROADENED_TERMS"

    def test_shortlist_reports_the_ceiling_that_excluded_everything(self) -> None:
        from neura_agent_sell.nodes.shortlist import _constraint_miss

        miss = _constraint_miss(
            [
                ("1305", "Product 1305: Linen Drawstring\n  price: 44.00 USD"),
                ("1307", "Product 1307: Halden Cargo\n  price: 62.00 USD"),
            ],
            {"entities": {"max_price": "40"}},
        )
        assert miss == {
            "kind": "constraint",
            "found": "2",
            "ceiling": "40.00",
            "cheapest": "44.00",
            "currency": "USD",
        }


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


class TestEvidenceFilter:
    """ADR-0025 — `verify` reads only what the draft cites.

    Measured cause in `scripts/verify_probe.py` arms E/F/G: an injected product
    the draft never mentions flips the verifier from 10/10 grounded to 10/10
    refused, and a benign third product of the same shape does not.
    """

    def _shortlist(self) -> str:
        """A real shortlist, from the real renderer. Never a hand-written one.

        The filter is anchored to the exact text `tools/render.py` produces, so
        a hand-written fixture here would keep passing on the day the renderer
        changed and the filter silently stopped matching anything.
        """
        store = load_store("t_test")
        products = {p.external_id: p for p in store._products.values()}
        entries = [
            render.candidate(products[pid]) for pid in ("p_jacket_1", "p_jacket_2", "p_injected")
        ]
        return '<tool_result name="search_products">\n' + "\n\n".join(entries) + "\n</tool_result>"

    def test_an_uncited_products_description_is_withheld(self) -> None:
        evidence = self._shortlist()
        assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in evidence, "the fixture must carry the payload"

        filtered = hide_uncited_descriptions(
            "The Crag Lightweight Rain Shell (p_jacket_2) is 129.00 GBP.", evidence
        )
        assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in filtered
        assert WITHHELD in filtered

    def test_a_cited_products_description_survives(self) -> None:
        """Otherwise the filter removes the evidence for the claim being checked."""
        filtered = hide_uncited_descriptions(
            "The Fell Waterproof Jacket (p_jacket_1) has taped seams.", self._shortlist()
        )
        assert "taped seams and a 10,000mm hydrostatic head" in filtered

    def test_price_and_availability_survive_for_every_product(self) -> None:
        """The `recommend_004` catch lives in `available options`, not in prose.

        `compose` claiming a boot is "available in UK 9" against evidence that
        says UK 9 is out of stock is the worst failure the eval found. Dropping
        whole entries would have traded one failure for a worse one.
        """
        store = load_store("t_test")
        boot = next(p for p in store._products.values() if p.external_id == "p_boot_1")
        evidence = f'<tool_result name="search_products">\n{render.candidate(boot)}\n</tool_result>'

        filtered = hide_uncited_descriptions("I recommend nothing at all.", evidence)
        assert "Product p_boot_1" in filtered
        assert "165.00 GBP" in filtered
        assert "UK 9 (out of stock)" in filtered

    def test_the_withholding_is_stated_not_silent(self) -> None:
        """A model shown nothing concludes there was nothing (`render.py`)."""
        filtered = hide_uncited_descriptions("nothing cited", self._shortlist())
        assert filtered.count(WITHHELD) == 3, "every uncited description says so"

    def test_text_outside_a_product_entry_is_untouched(self) -> None:
        evidence = 'Retrieved policy: returns within 30 days.\n\n<tool_result name="x">\nProduct p_a: A\n  description: hello\n</tool_result>'
        filtered = hide_uncited_descriptions("nothing", evidence)
        assert "Retrieved policy: returns within 30 days." in filtered

    def test_an_empty_evidence_block_is_returned_unchanged(self) -> None:
        """`verify`'s empty-evidence branch reads the FULL evidence, but this
        must not be the thing that makes it empty."""
        assert hide_uncited_descriptions("anything", "") == ""

    def test_citation_parsing_agrees_with_respond(self) -> None:
        """The two must agree, or this file withholds evidence for a product
        `respond` considers cited — so they share one function, not two copies."""
        # `importlib`, because `neura_agent_sell.nodes` exports the `respond`
        # function under the module's own name.
        respond_module = importlib.import_module("neura_agent_sell.nodes.respond")
        assert evidence_module.cited_ids is respond_module.cited_ids is cited_ids

    def _short_id_shortlist(self) -> str:
        store = load_store("t_test", ["short_ids.json"])
        products = {p.external_id: p for p in store._products.values()}
        entries = [render.candidate(products[pid]) for pid in ("4", "5")]
        return '<tool_result name="search_products">\n' + "\n\n".join(entries) + "\n</tool_result>"

    def test_a_one_character_id_is_cited(self) -> None:
        """G36: products `3`, `4`, `5` on a connected shop were never seen as cited,
        so a claim copied from product 4's description failed `verify`."""
        evidence = self._short_id_shortlist()
        filtered = hide_uncited_descriptions(
            "The Enamel Camp Mug 350ml (Product 4) is safe to heat on a camp stove.", evidence
        )
        assert "Safe to heat directly on a camp stove" in filtered, "the cited description stays"
        assert "Not for use over a flame" not in filtered, "the uncited one is still withheld"
        assert filtered.count(WITHHELD) == 1


class TestCitedIds:
    """`citations.cited_ids` — known ids, as whole tokens, in the order named."""

    def test_short_ids_are_found(self) -> None:
        assert cited_ids("Try the mug (Product 4) or product 5.", ["3", "4", "5"]) == ["4", "5"]

    def test_an_id_inside_a_longer_word_or_number_is_not(self) -> None:
        draft = "A 400g pack at 4.50 GBP, item p_4, 14 in a box, 4-pack."
        assert cited_ids(draft, ["4", "p", "0"]) == []

    def test_order_follows_the_draft(self) -> None:
        assert cited_ids("First p_boot_1, then p_jacket_1.", ["p_jacket_1", "p_boot_1"]) == [
            "p_boot_1",
            "p_jacket_1",
        ]

    def test_long_ids_behave_as_before(self) -> None:
        draft = "The **Moor Walking Boot (p_boot_1)** and the Fell (p_jacket_1) are both good."
        assert cited_ids(draft, ["p_boot_1", "p_jacket_1", "p_jacket_2"]) == [
            "p_boot_1",
            "p_jacket_1",
        ]

    def test_only_known_ids_are_looked_for(self) -> None:
        assert cited_ids("The Fell jacket is waterproof.", []) == []


class TestWithoutIds:
    """G41: the shopper read "Ceylon Black Tea BOPF 400g (Product 4)"."""

    def test_a_bracketed_id_is_removed(self) -> None:
        reply = "I recommend the Ceylon Black Tea BOPF 400g (Product 4), which is 1850 LKR."
        assert without_ids(reply, ["4"]) == (
            "I recommend the Ceylon Black Tea BOPF 400g, which is 1850 LKR."
        )

    def test_every_bracket_shape_is_removed(self) -> None:
        reply = "The **Moor Walking Boot (p_boot_1)**, the mug [4] or the cup (product id 5)."
        assert without_ids(reply, ["4", "5", "p_boot_1"]) == (
            "The **Moor Walking Boot**, the mug or the cup."
        )

    def test_the_shoppers_own_numbers_stay(self) -> None:
        reply = "Brew 4 cups; size 4 fits (4 pack)."
        assert without_ids(reply, ["4"]) == reply

    def test_an_unknown_id_in_brackets_stays(self) -> None:
        assert without_ids("A pack (p_other).", ["4"]) == "A pack (p_other)."

    def test_an_id_before_its_name_is_removed(self) -> None:
        """G106: Gemini wrote it the other way round, and the id stayed."""
        reply = "Product 4 (Ceylon Black Tea BOPF 400g) is in stock at 1850 LKR."
        assert without_ids(reply, ["4"]) == "Ceylon Black Tea BOPF 400g is in stock at 1850 LKR."

    def test_every_shape_of_an_id_before_its_name_is_removed(self) -> None:
        reply = "Try **Product 4 (Ceylon Black Tea)** or product id p_boot_1 (Moor Walking Boot)."
        assert (
            without_ids(reply, ["4", "p_boot_1"])
            == "Try **Ceylon Black Tea** or Moor Walking Boot."
        )

    def test_a_number_before_brackets_without_the_word_product_stays(self) -> None:
        reply = "Size 4 (UK) fits, and 4 (four) bags come in a box."
        assert without_ids(reply, ["4"]) == reply

    def test_an_unknown_id_before_a_name_stays(self) -> None:
        assert without_ids("Product 9 (Mug) is not ours.", ["4"]) == "Product 9 (Mug) is not ours."

    def test_an_id_and_a_comma_before_its_name_are_removed(self) -> None:
        """G106, seen again on Gemini: "I recommend Product 4, the Enamel Camp Mug"."""
        reply = "I recommend Product 4, the Enamel Camp Mug 350ml, which costs 12.00 GBP."
        assert without_ids(reply, ["4"]) == (
            "I recommend the Enamel Camp Mug 350ml, which costs 12.00 GBP."
        )

    def test_compose_says_how_to_write_an_id(self) -> None:
        """G106: told only to "use those exact ids", the model invented a form each time."""
        from neura_agent_sell.prompts import load_prompts

        compose = " ".join(load_prompts()["compose"].split())
        assert "in brackets straight after the product's name" in compose
        assert 'Never write "Product' in compose
