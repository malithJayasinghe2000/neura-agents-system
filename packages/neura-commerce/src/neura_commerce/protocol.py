"""The commerce adapter contract.

**This is the most important interface in the codebase.** Everything above it —
agents, tools, retrieval, the API — speaks only the canonical domain model.
Adapters translate. Nothing else learns that any particular platform exists.

A ``typing.Protocol`` rather than an abstract base class, deliberately: adapters
are matched structurally, so a third party can implement one without importing
anything from us. That matters for the published integration spec — an
integrator should not need our package to be compatible with us.

Two rules for implementors:

* **Declare capabilities honestly.** Over-declaring produces tools that fail at
  runtime; under-declaring only costs a feature. Err downward.
* **Return canonical models, never platform payloads.** Keep the original in
  ``raw`` if it is useful, but a platform's own status strings must never reach
  the agent, or the agent starts reasoning about a vocabulary only one platform
  uses.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from neura_commerce.pagination import Cursor, Page
from neura_commerce.queries import HealthStatus, ProductQuery, SyncQuery
from neura_domain import (
    Address,
    Capability,
    Category,
    Customer,
    CustomerRef,
    InventoryLevel,
    Order,
    Policy,
    Product,
)


@runtime_checkable
class CommerceAdapter(Protocol):
    """What a commerce platform must provide.

    Only the read surface is required. Write methods are optional and gated by
    both capability and the approval queue — the MVP registers no write tools at
    all (docs/architecture/adr/0010-read-only-mvp-tools.md).
    """

    #: Platform identifier, e.g. "generic". Appears on every entity's provenance.
    platform: ClassVar[str]

    #: What this platform can do. Drives which tools the agent is given, so an
    #: unsupported operation becomes structurally impossible rather than merely
    #: discouraged.
    capabilities: ClassVar[frozenset[Capability]]

    # ── Connectivity ─────────────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        """Reachability plus self-declared capabilities.

        Called at connection time so a merchant learns immediately that an agent
        will not work for their store, rather than discovering it through a
        failed conversation.
        """
        ...

    # ── Catalogue ────────────────────────────────────────────────────────────

    async def get_product(self, external_id: str) -> Product | None:
        """``None`` when absent — not an error. Customers mistype ids routinely."""
        ...

    async def search_products(self, query: ProductQuery) -> Page[Product]:
        """Search. An empty page is a valid result, never an error."""
        ...

    async def list_products(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Product]:
        """Bulk crawl for sync. Must be stable enough to resume from a cursor."""
        ...

    async def list_categories(self) -> list[Category]: ...

    async def get_inventory(self, variant_external_ids: list[str]) -> list[InventoryLevel]:
        """Stock levels. Missing variants are omitted rather than raising."""
        ...

    # ── Orders ───────────────────────────────────────────────────────────────

    async def get_order(self, external_id: str) -> Order | None:
        """One order.

        This returns data regardless of who is asking — **the adapter is not an
        authorisation boundary.** Whether the caller may see this order is
        decided by ownership verification in the policy engine
        (docs/architecture/security-model.md §3). Putting that check here would
        scatter a security control across every adapter.
        """
        ...

    async def list_orders(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Order]: ...

    async def find_orders_for_customer(self, ref: CustomerRef) -> list[Order]:
        """Orders for a customer identified by id, email or phone.

        Needed because a shopper in a chat window usually knows their email, not
        their customer id.
        """
        ...

    # ── Customers ────────────────────────────────────────────────────────────

    async def get_customer(self, external_id: str) -> Customer | None: ...

    # ── Store content ────────────────────────────────────────────────────────

    async def get_policies(self) -> list[Policy]:
        """Returns, shipping and warranty text the agent grounds answers in."""
        ...


@runtime_checkable
class WritableCommerceAdapter(CommerceAdapter, Protocol):
    """Optional write surface. Phase 2.

    Separate protocol so a read-only adapter is a complete, valid adapter rather
    than one with unimplemented methods. Every method here requires
    ``Capability.ORDER_WRITE`` **and** human approval before execution.
    """

    async def cancel_order(self, external_id: str, reason: str) -> Order: ...

    async def update_shipping_address(self, external_id: str, address: Address) -> Order: ...
