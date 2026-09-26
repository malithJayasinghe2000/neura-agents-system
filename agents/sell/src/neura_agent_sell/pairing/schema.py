"""The ``sell_pairings`` table — one computed pairing per product, per store.

[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
in DDL. Four of its decisions are load-bearing here rather than in prose.

**A pairing, never an availability** (§4). The row holds product *ids* and the
kinds that found them. It holds no price, no stock level, no status and no
title: every one of those is read live from the merchant's shop on the request
that renders them, so a pairing computed in July cannot state a fact about
October.

**Per product, never per person** (§2). The natural key is
``(tenant, store, product)``. There is no shopper here — no session, no
visitor, no cookie, nothing that identifies anybody — because the thing being
cached is *what goes with a walking boot*, which is the same answer for every
shopper who ever has one in a basket. That is not an efficiency; it is
[ADR-0042](../../../../../docs/architecture/adr/0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md)
holding, and a ``visitor_id`` column would be the shape of breaking it.

**``source_hash`` is the invalidation** (§5). It fingerprints the product text
the model actually read. When the merchant rewrites the description the hash
stops matching and the stored pairing is not used — *"a stale pairing is a wrong
suggestion with a long life"*, which is worse than no cache at all. A timestamp
would have answered a different question: how old the row is, rather than
whether it still describes the product.

**``kinds``, ``model`` and ``prompt_hash`` are the audit trail**, and they are
the reason a merchant asking *"why was I shown a frock?"* has an answer six
weeks later. A model chose this; which model, on which prompt, having asked for
what, is exactly the record ``prompts/__init__.py`` exists to make possible for
every other model call in this system.

**Defined here, in the agent that owns it**, like ``sell_feeds`` — dependencies
point downward and ``agents/`` → ``neura-core`` is downward. It carries
``tenant_id``, so the ADR-0008 protection test covers it automatically.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, String, Table, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from neura_core import metadata

SELL_PAIRINGS = "sell_pairings"

sell_pairings = Table(
    SELL_PAIRINGS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    #: Which store's catalogue these ids belong to. A product id means nothing
    #: without one — two shops can both have a product `1315`, and a pairing
    #: that crossed them would suggest a stranger's catalogue.
    Column("store_id", String(64), nullable=False),
    #: The anchor's external id, in the merchant's own numbering. `String(128)`
    #: matches the bound `_clean_ids` puts on an id arriving from a page.
    Column("product_id", String(128), nullable=False),
    #: SHA-256 of the anchor's title and description as the model read them.
    #: The pairing is used only while this still matches the live product.
    Column("source_hash", String(64), nullable=False),
    #: The merchant's own product ids, in the order the model's kinds found
    #: them. More than a shopper is shown, on purpose — `compute.MAX_STORED_IDS`
    #: explains why the spares are there.
    Column("suggested_ids", JSONB, nullable=False, server_default="[]"),
    #: What the model asked the catalogue for. Diagnostics only: nothing reads
    #: this to decide what a shopper sees.
    Column("kinds", JSONB, nullable=False, server_default="[]"),
    #: Which model produced it, and which prompt it was given. Both change under
    #: a role-map swap, and a pairing nobody can attribute is a suggestion
    #: nobody can explain.
    Column("model", String(128), nullable=False, server_default=""),
    Column("prompt_hash", String(64), nullable=False, server_default=""),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    #: Why this row holds nothing, when it holds nothing. An empty pairing is a
    #: **result** (ADR-0040 §4) and is stored as one, so a product whose kinds
    #: match nothing in the catalogue is not recomputed on every cart page for
    #: ever. The text says which of the several empties it was.
    Column("note", Text, nullable=False, server_default=""),
    # One pairing per product per store. The upsert infers this constraint, so
    # a recomputation replaces rather than accumulates.
    UniqueConstraint("tenant_id", "store_id", "product_id", name="uq_sell_pairings_product"),
    # The read, and it is on a cart page: tenant and store are already known,
    # the product id is the lookup.
    Index("ix_sell_pairings_tenant_store_product", "tenant_id", "store_id", "product_id"),
)

__all__ = ["SELL_PAIRINGS", "sell_pairings"]
