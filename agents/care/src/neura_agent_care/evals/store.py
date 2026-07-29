"""A store made of fixture files, for evals.

An eval must be *reproducible*. Running CARE against the live test shop would
mean a case's expected answer changes the day somebody edits a product, and a
suite whose failures are ambiguous between "the agent regressed" and "the shop
changed" is a suite nobody trusts enough to act on. So the golden dataset gets a
store it can pin.

This is not a substitute for running against a real platform — that is
``make care-check``, and it is where the bugs actually get found. The two answer
different questions: the smoke test asks "does this work against a real store?",
the eval asks "did today's change make it worse than yesterday's?".

**Fixtures carry business fields only.** Provenance — ``neura_id``,
``tenant_id``, ``platform``, ``synced_at`` — is filled in here, exactly as
milestone 1.6 decided the spec would do for a real store: those five fields are
never accepted from the other side of a boundary. It also keeps the JSON
readable by the people best placed to say "a customer would never phrase it like
that", who are support staff rather than engineers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from neura_commerce import Cursor, HealthStatus, Page, ProductQuery, SyncQuery
from neura_domain import (
    Capability,
    Category,
    Customer,
    CustomerRef,
    InventoryLevel,
    Order,
    Policy,
    Product,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

#: Loaded for every case, then overlaid with whatever the case names. Holds the
#: catalogue and the policy pages — the things every conversation may touch.
BASE_FIXTURE = "store.json"

#: Not a real platform, and deliberately so. A fixture store is its own thing;
#: naming a commerce product here would put a platform name in a core package
#: and break the check that keeps the market position honest (AGENTS.md rule 1).
PLATFORM = "fixture"

#: Everything a fixture store can do. Cases that need a *reduced* store — to
#: check that a tool vanishes when a capability is absent — pass their own set.
ALL_CAPABILITIES = frozenset(
    {
        Capability.PRODUCT_READ,
        Capability.PRODUCT_SEARCH,
        Capability.CATEGORY_READ,
        Capability.INVENTORY_READ,
        Capability.ORDER_READ,
        Capability.ORDER_SEARCH,
        Capability.CUSTOMER_READ,
        Capability.POLICY_READ,
    }
)

_SYNCED_AT = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class FixtureError(RuntimeError):
    """A fixture is missing or malformed. Raised at load time, before any case runs."""


class FixtureStore:
    """A commerce store whose data comes from JSON on disk.

    Satisfies ``CommerceAdapter`` structurally — no import, no base class, the
    same way a third party conforms to the published spec. If this class ever
    stops satisfying it, that is a signal the protocol changed, and a test
    asserts it at the protocol level rather than by duck-typing at runtime.
    """

    platform: ClassVar[str] = PLATFORM

    def __init__(
        self,
        *,
        tenant_id: str,
        products: list[Product] | None = None,
        orders: list[Order] | None = None,
        customers: list[Customer] | None = None,
        policies: list[Policy] | None = None,
        categories: list[Category] | None = None,
        inventory: list[InventoryLevel] | None = None,
        capabilities: frozenset[Capability] = ALL_CAPABILITIES,
    ) -> None:
        self.tenant_id = tenant_id
        self.capabilities = capabilities
        self._products = {p.external_id: p for p in products or []}
        self._orders = {o.external_id: o for o in orders or []}
        self._customers = {c.external_id: c for c in customers or []}
        self._policies = list(policies or [])
        self._categories = list(categories or [])
        self._inventory = {i.variant_external_id: i for i in inventory or []}

    # ── Connectivity ─────────────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=True, platform=PLATFORM, capabilities=self.capabilities)

    # ── Catalogue ────────────────────────────────────────────────────────────

    async def get_product(self, external_id: str) -> Product | None:
        return self._products.get(external_id)

    async def search_products(self, query: ProductQuery) -> Page[Product]:
        """Substring matching over title and description, tolerating plurals.

        Crude on purpose: a fixture store that ranked cleverly would flatter the
        agent, and the eval would be measuring a search engine no merchant has.

        But it must not be crude in the *other* direction either, and the first
        version was. Requiring an exact substring meant "waterproof walking
        shoes" matched nothing in a catalogue selling a "Waterproof Hiking Shoe",
        purely on the trailing "s" — so the case failed, the agent was blamed,
        and what had actually been measured was whether the model guessed the
        catalogue's exact choice of singular noun. Every real shop's search stems
        plurals; a fake that is meaningfully worse than the thing it stands in for
        produces failures nobody can act on.
        """
        terms = (query.text or "").lower().split()
        matches = [
            product
            for product in self._products.values()
            if all(
                _matches(term, f"{product.title} {product.description or ''}".lower())
                for term in terms
            )
        ]
        return Page(items=matches[: query.limit])

    async def list_products(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Product]:
        return Page(items=list(self._products.values())[: query.limit])

    async def list_categories(self) -> list[Category]:
        return list(self._categories)

    async def get_inventory(self, variant_external_ids: list[str]) -> list[InventoryLevel]:
        # Missing variants are omitted, never invented — the protocol says so,
        # and a store that returned a zero for an id it has never seen would let
        # the agent report "out of stock" about a product that does not exist.
        return [self._inventory[v] for v in variant_external_ids if v in self._inventory]

    # ── Orders ───────────────────────────────────────────────────────────────

    async def get_order(self, external_id: str) -> Order | None:
        return self._orders.get(external_id)

    async def list_orders(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Order]:
        return Page(items=list(self._orders.values())[: query.limit])

    async def find_orders_for_customer(self, ref: CustomerRef) -> list[Order]:
        """Match on whichever identifier was supplied.

        **No identifier means no orders**, matching ``GenericAdapter``. Returning
        everything would be both useless and the exact shape of a
        data-exfiltration bug, so the fixture store reproduces the real
        behaviour rather than being lenient — a fake that is more permissive than
        the thing it stands in for hides the bug it was built to catch.
        """
        if not any((ref.external_id, ref.email, ref.phone, ref.order_ref)):
            return []

        return [
            order
            for order in self._orders.values()
            if (ref.external_id and order.customer_external_id == ref.external_id)
            or (ref.email and order.customer_email == ref.email)
            or (ref.order_ref and order.order_number == ref.order_ref)
        ]

    # ── Customers ────────────────────────────────────────────────────────────

    async def get_customer(self, external_id: str) -> Customer | None:
        return self._customers.get(external_id)

    # ── Store content ────────────────────────────────────────────────────────

    async def get_policies(self) -> list[Policy]:
        return list(self._policies)


def load_store(
    tenant_id: str,
    fixtures: list[str],
    *,
    capabilities: frozenset[Capability] = ALL_CAPABILITIES,
) -> FixtureStore:
    """Build a store from the base fixture plus whatever a case names.

    Later files win on a collision, keyed by ``external_id``, so a case can
    override one product or one order without restating the catalogue.
    """
    payload = _merge([_read(BASE_FIXTURE)] + [_read(name) for name in fixtures])

    return FixtureStore(
        tenant_id=tenant_id,
        products=[_entity(Product, tenant_id, item) for item in payload.get("products", [])],
        orders=[_entity(Order, tenant_id, item) for item in payload.get("orders", [])],
        customers=[_entity(Customer, tenant_id, item) for item in payload.get("customers", [])],
        policies=[_entity(Policy, tenant_id, item) for item in payload.get("policies", [])],
        categories=[_entity(Category, tenant_id, item) for item in payload.get("categories", [])],
        inventory=[InventoryLevel.model_validate(i) for i in payload.get("inventory", [])],
        capabilities=capabilities,
    )


def _matches(term: str, haystack: str) -> bool:
    """One search term against one product's text.

    Handles the plural forms an English-speaking shopper types and a catalogue
    does not use. Deliberately not a stemmer: "shoes"/"shoe" and
    "batteries"/"battery" are the cases that occur, and anything more ambitious
    would start making matches the eval cannot explain.
    """
    if term in haystack:
        return True
    if term.endswith("ies") and f"{term[:-3]}y" in haystack:
        return True
    if term.endswith("es") and term[:-2] in haystack:
        return True
    return term.endswith("s") and term[:-1] in haystack


def _read(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    if not path.exists():
        # Named loudly. A case referencing a fixture that does not exist would
        # otherwise run against an empty store and fail for a reason that looks
        # like an agent bug.
        raise FixtureError(
            f"fixture {name!r} does not exist in {FIXTURE_DIR}. "
            f"Available: {sorted(p.relative_to(FIXTURE_DIR).as_posix() for p in FIXTURE_DIR.rglob('*.json'))}"
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"fixture {name!r} is not valid JSON: {exc}") from exc

    if not isinstance(loaded, dict):
        raise FixtureError(f"fixture {name!r} must be a JSON object of entity lists")
    return loaded


def _merge(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Overlay fixtures in order, later files winning per ``external_id``.

    Keys beginning with an underscore are notes for whoever reads the file, not
    entities. Fixtures explain *why* a case needs the data it needs, and that
    explanation is the most valuable line in most of them.
    """
    merged: dict[str, list[dict[str, Any]]] = {}
    for payload in payloads:
        for entity_type, items in payload.items():
            if entity_type.startswith("_"):
                continue
            merged.setdefault(entity_type, [])
            for item in items:
                merged[entity_type] = [
                    existing
                    for existing in merged[entity_type]
                    if existing.get("external_id") != item.get("external_id")
                ]
                merged[entity_type].append(item)
    return merged


def _entity[EntityT](model: type[EntityT], tenant_id: str, payload: dict[str, Any]) -> EntityT:
    """Validate a fixture entity, filling in provenance.

    The five provenance fields are supplied here and are *not* read from the
    fixture, deliberately mirroring the spec's rule: a store cannot know its
    ``tenant_id`` or ``neura_id`` and must not be trusted to assert ``platform``
    (milestone 1.6). A fixture that tried to set them would be quietly ignored,
    which is the same outcome a real store gets.
    """
    external_id = str(payload.get("external_id", ""))
    if not external_id:
        raise FixtureError(f"a {model.__name__} fixture has no external_id: {payload}")

    return model(  # type: ignore[call-arg]
        **{k: v for k, v in payload.items() if k not in _PROVENANCE},
        neura_id=f"{model.__name__.lower()}_{external_id}",
        tenant_id=tenant_id,
        external_id=external_id,
        platform=PLATFORM,
        synced_at=_SYNCED_AT,
    )


_PROVENANCE = frozenset({"neura_id", "tenant_id", "external_id", "platform", "synced_at"})

__all__ = [
    "ALL_CAPABILITIES",
    "BASE_FIXTURE",
    "FIXTURE_DIR",
    "PLATFORM",
    "FixtureError",
    "FixtureStore",
    "load_store",
]
