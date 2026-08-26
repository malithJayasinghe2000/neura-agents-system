"""The ``sell_feeds`` table — one publication switch per store, with its secret.

[ADR-0024](../../../../../docs/architecture/adr/0024-the-feed-is-opt-in-and-addressed-by-a-rotatable-secret.md)
in DDL. Three of its decisions are load-bearing here rather than in prose.

**Its own table, not an ``ApiKeyKind.FEED`` row in ``api_keys``.** Reusing that
table was genuinely tempting — hashing, revocation, ``last_used_at`` and the
prefix display all already exist there. It is refused because **a secret in a
URL path is not a bearer token**: URLs are written to proxy logs, kept in
browser history, pasted into chat and sent in ``Referer`` headers. One table
whose rows are sometimes `Authorization` credentials and sometimes URL segments
is a table where somebody eventually treats one as the other, and the direction
that mistake runs is unrecoverable.

**Off is the absence of a row, not a boolean.** There is no ``enabled`` column.
A tenant with no row publishes nothing, so the default state is not a value
anybody can set wrongly — it is the absence of a decision. A boolean would give
a future migration, backfill or admin script a way to switch publication *on*
for every merchant at once, and publication cannot be undone (ADR-0024).

**Defined here, in the agent that owns it, against ``neura_core.metadata``.**
Dependencies point downward and ``agents/`` → ``neura-core`` is downward, so an
agent may define its own tables; what it may not do is put them in a shared
package where every other agent inherits them.

It carries ``tenant_id``, so it is covered automatically by the ADR-0008
protection test that scans for exactly that column — RLS enabled, forced, and a
policy, or the suite fails. That coverage is deliberate rather than lucky: the
one thing a feed row must never do is answer for a tenant other than its own.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, String, Table, UniqueConstraint, func

from neura_core import metadata

SELL_FEEDS = "sell_feeds"

sell_feeds = Table(
    SELL_FEEDS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    #: Which store's catalogue this publishes. A tenant has one store in MVP and
    #: the model allows more, so the feed is addressed per store rather than per
    #: tenant — otherwise the day a merchant connects a second shop, one of them
    #: silently starts publishing the other's products.
    Column("store_id", String(64), nullable=False),
    #: Displayable fragment, so a merchant with two feeds can tell them apart in
    #: a list. Never enough of the token to reconstruct it.
    Column("token_prefix", String(64), nullable=False),
    #: SHA-256 of the token. The plaintext exists once, in the response that
    #: created it, and is never recoverable — which is why rotation rather than
    #: retrieval is the answer when a merchant loses their URL.
    Column("token_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    #: Set when this feed's token is replaced. The row is kept rather than
    #: deleted: "this feed was rotated on the 3rd" is the answer to a merchant
    #: asking why their submitted URL stopped working, and a deleted row answers
    #: nothing. A rotated row never resolves — the lookup filters it out.
    Column("rotated_at", DateTime(timezone=True), nullable=True),
    #: Observability, and the only way a merchant learns their feed is actually
    #: being read. Written on a schedule rather than per request; see the
    #: repository.
    Column("last_served_at", DateTime(timezone=True), nullable=True),
    # Global, not per-tenant, and for the same reason `api_keys` does it: the
    # same hash under two tenants would make one URL resolve to either, and
    # which one you got would depend on the plan.
    UniqueConstraint("token_hash", name="uq_sell_feeds_token_hash"),
    Index("ix_sell_feeds_tenant_id_store_id", "tenant_id", "store_id"),
)

__all__ = ["SELL_FEEDS", "sell_feeds"]
