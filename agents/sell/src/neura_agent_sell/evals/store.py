"""A store made of fixture files, for SELL's evals.

An eval must be *reproducible*. Running SELL against the live test shop would
mean a case's expected shortlist changes the day somebody edits a product, and a
suite whose failures are ambiguous between "the agent regressed" and "the shop
changed" is one nobody trusts enough to act on.

This is not a substitute for running against a real platform. The two answer
different questions: a smoke run asks "does this work against a real store?",
the eval asks "did today's change make it worse than yesterday's?".

**Narrower than CARE's fixture store, and that narrowness is the design.** SELL
has no order tools, no customer tools and no policy tools, so this implements
the catalogue half of ``CommerceAdapter`` and nothing else. A fixture that
served orders would be offering SELL a surface it does not have — and would make
"SELL never reads a person" a claim about the fixtures rather than about the
agent.

**Fixtures carry business fields only.** Provenance — ``neura_id``,
``tenant_id``, ``platform``, ``synced_at`` — is filled in here, exactly as the
published spec strips it for a real store: those fields are never accepted from
the other side of a boundary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from neura_commerce import Cursor, HealthStatus, Page, ProductQuery, SyncQuery
from neura_domain import Capability, Category, CustomerRef, InventoryLevel, Order, Product

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

BASE_FIXTURE = "store.json"

#: Not a real platform, deliberately. Naming a commerce product here would put a
#: platform name outside the adapters package and break the check that keeps the
#: market position honest (AGENTS.md rule 1).
PLATFORM = "fixture"

SYNCED_AT = datetime(2026, 8, 26, tzinfo=UTC)

#: Everything a fixture store can do. Cases needing a *reduced* store — to check
#: that a tool vanishes when a capability is absent — pass their own set.
ALL_CAPABILITIES = frozenset(
    {
        Capability.PRODUCT_READ,
        Capability.PRODUCT_SEARCH,
        Capability.CATEGORY_READ,
        Capability.INVENTORY_READ,
    }
)


class FixtureStore:
    """A ``CommerceAdapter`` over JSON files. Catalogue only."""

    capabilities: ClassVar[frozenset[Capability]] = ALL_CAPABILITIES

    def __init__(self, tenant_id: str, products: list[Product], categories: list[Category]) -> None:
        self._tenant_id = tenant_id
        self._products = {p.external_id: p for p in products}
        self._categories = categories

    # ── Health ───────────────────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=True, platform=PLATFORM, capabilities=frozenset(self.capabilities))

    # ── Catalogue ────────────────────────────────────────────────────────────

    async def search_products(self, query: ProductQuery) -> Page[Product]:
        """Substring matching over title and description, tolerating plurals.

        Crude on purpose: a fixture store that ranked cleverly would flatter the
        agent, and the eval would be measuring a search engine no merchant has.

        It must not be crude in the *other* direction either. CARE's fixture
        store recorded the lesson — requiring an exact substring meant
        "waterproof walking shoes" matched nothing in a catalogue selling a
        "Waterproof Hiking Shoe", purely on a trailing "s". The case failed, the
        agent was blamed, and what was measured was whether the model guessed the
        catalogue's choice of singular noun.

        **Any term matching is enough here**, where CARE requires all of them.
        SELL is handed a *need* — "a waterproof jacket for hill walking in
        winter" — rather than a product name, and requiring every word to appear
        would return nothing for every realistic recommendation query. That is
        also closer to what a real storefront search does.
        """
        terms = [t for t in (query.text or "").lower().split() if len(t) > 2]
        if not terms:
            return Page(items=[])

        matches = [
            product
            for product in self._products.values()
            if any(
                _matches(term, f"{product.title} {product.description or ''}".lower())
                for term in terms
            )
        ]
        # Deterministic order: the fixture's own, so a case's expected shortlist
        # cannot change because a dict iterated differently.
        return Page(items=matches[: query.limit])

    async def get_product(self, external_id: str) -> Product | None:
        return self._products.get(external_id)

    async def list_products(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Product]:
        return Page(items=list(self._products.values()))

    async def list_categories(self) -> list[Category]:
        return list(self._categories)

    async def get_inventory(self, variant_external_ids: list[str]) -> list[InventoryLevel]:
        """Live stock for the variants named.

        A variant this store does not know is **omitted**, not reported as out
        of stock — which is what a real adapter does, and what makes
        `inventory_evidence`'s "availability unknown" path reachable in a test.
        """
        levels = []
        for product in self._products.values():
            for variant in product.variants:
                if variant.external_id in variant_external_ids:
                    levels.append(
                        InventoryLevel(
                            variant_external_id=variant.external_id,
                            quantity=variant.stock_quantity or 0,
                            in_stock=bool(variant.in_stock),
                        )
                    )
        return levels

    # ── Absent on purpose ────────────────────────────────────────────────────
    #
    # SELL has no order, customer or policy tool, so this fixture implements
    # none of them. Raising rather than returning empty: a silent empty result
    # would let a future tool read orders here and pass its eval against a store
    # that answered "no orders" to everything.

    async def get_order(self, external_id: str) -> Order | None:
        raise NotImplementedError("SELL has no order tools — see evals/store.py")

    async def find_orders_for_customer(self, ref: CustomerRef) -> list[Order]:
        raise NotImplementedError("SELL has no order tools — see evals/store.py")

    async def get_policies(self) -> list[Any]:
        raise NotImplementedError("SELL has no policy tools — see evals/store.py")


def load_store(tenant_id: str, extra_fixtures: list[str] | None = None) -> FixtureStore:
    """Build the fixture store a case runs against."""
    data = _read(BASE_FIXTURE)

    for name in extra_fixtures or []:
        overlay = _read(name)
        for key, value in overlay.items():
            if key.startswith("_"):
                continue
            data.setdefault(key, [])
            data[key] = list(data[key]) + list(value)

    products = [_product(tenant_id, raw) for raw in data.get("products", [])]
    categories = [_category(tenant_id, raw) for raw in data.get("categories", [])]
    return FixtureStore(tenant_id, products, categories)


def _read(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"no fixture named {name!r} in {FIXTURE_DIR}")
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _provenance(tenant_id: str, external_id: str) -> dict[str, Any]:
    return {
        "neura_id": f"fx_{external_id}",
        "tenant_id": tenant_id,
        "platform": PLATFORM,
        "synced_at": SYNCED_AT,
    }


def _product(tenant_id: str, raw: dict[str, Any]) -> Product:
    body = {k: v for k, v in raw.items() if not k.startswith("_")}
    return Product(**_provenance(tenant_id, body["external_id"]), **body)


def _category(tenant_id: str, raw: dict[str, Any]) -> Category:
    body = {k: v for k, v in raw.items() if not k.startswith("_")}
    return Category(**_provenance(tenant_id, body["external_id"]), **body)


def _matches(term: str, haystack: str) -> bool:
    """Does this term appear, allowing for a plural on either side?"""
    if term in haystack:
        return True
    if term.endswith("s") and term[:-1] in haystack:
        return True
    return f"{term}s" in haystack


__all__ = ["ALL_CAPABILITIES", "PLATFORM", "FixtureStore", "load_store"]
