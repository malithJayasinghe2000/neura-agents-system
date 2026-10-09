"""The four tables tenancy is made of.

Defined against ``neura_core.metadata`` so Alembic can diff them. The DDL that
creates them — including every Row-Level Security policy, which SQLAlchemy does
not model — lives in the migration, and
``tests/integration/test_migrations.py`` fails if any table here carries a
``tenant_id`` without a forced policy.

**Why ``tenants`` names its primary key ``tenant_id`` rather than ``id``.** The
conventional name would make the tenant table the one tenant-scoped table that
the "every table with a ``tenant_id`` is protected" test cannot see, because the
column it looks for would not exist — the same hole ADR-0008 warns about for
LangGraph's checkpoint tables. Naming it ``tenant_id`` costs one small oddity
and buys automatic coverage for the table whose leakage would expose every
merchant's name at once.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import BigInteger, Date

from neura_core.db import metadata

TENANTS = "tenants"
API_KEYS = "api_keys"
TENANT_STORES = "tenant_stores"
TENANT_USAGE = "tenant_usage"
SHOP_TOKENS = "shop_tokens"
SHOP_CHECKS = "shop_checks"
CUSTOMER_SECRETS = "customer_secrets"


#: One merchant. The row that has to exist before anything else in the system
#: means anything.
#:
#: ``enabled_agents`` is the entitlement layer from
#: tenancy-and-packaging.md §3 — the field that makes one codebase sell as
#: separate products. ``config`` is the behavioural knobs; typed columns are
#: reserved for what the platform *enforces*, so that what is enforced is
#: always queryable and constrained (ADR-0013).
tenants = Table(
    TENANTS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("status", String(32), nullable=False, server_default="active"),
    Column("enabled_agents", JSONB, nullable=False, server_default="[]"),
    Column("config", JSONB, nullable=False, server_default="{}"),
    #: When a data-processing agreement with this merchant was recorded, and
    #: ``NULL`` if none has been. ADR-0042 §2: *"no tenant stores personal data
    #: until a data-processing agreement is in place — it is a row in the tenant
    #: record, not a handshake."* A typed column rather than a key in ``config``
    #: because it is **enforced** (ADR-0013): an ``observe:write`` key cannot be
    #: issued without it, and the event route refuses without it.
    Column("dpa_signed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


#: Our own API keys — ``fn_sk_…`` server-side and ``fn_pk_…`` for the widget
#: (api-design.md §2, security-model.md §5).
#:
#: The plaintext is never stored. ``token_hash`` is a SHA-256 of the whole key
#: and is the only thing authentication compares; ``token_prefix`` is a
#: displayable fragment so a merchant can tell two keys apart in a list without
#: either of them being recoverable (ADR-0014).
api_keys = Table(
    API_KEYS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("name", String(128), nullable=False, server_default=""),
    Column("token_prefix", String(64), nullable=False),
    Column("token_hash", String(64), nullable=False),
    Column("scopes", JSONB, nullable=False, server_default="[]"),
    #: Public keys are origin-locked, because a key shipped to a browser is by
    #: definition readable by everyone who loads the page.
    Column("allowed_origins", JSONB, nullable=False, server_default="[]"),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Authentication looks up by hash and nothing else, so the uniqueness that
    # makes that lookup unambiguous is a database constraint rather than an
    # assumption. It is global rather than per-tenant on purpose: the same hash
    # under two tenants would make one token authenticate as either.
    UniqueConstraint("token_hash", name="uq_api_keys_token_hash"),
    Index("ix_api_keys_tenant_id_created_at", "tenant_id", "created_at"),
)


#: A tenant's connection to one commerce store.
#:
#: ``credentials`` is AES-256-GCM ciphertext and ``wrapped_dek`` is that
#: tenant's data key encrypted under the KEK, which lives in the environment and
#: never in this database (security-model.md §5). A dump of this table alone is
#: useless.
#:
#: ``platform`` holds a platform identifier as *data*. That is not a breach of
#: rule 1: the rule forbids this layer containing platform-specific behaviour,
#: and a string a merchant's own adapter reports is the opposite — it is how the
#: core stays ignorant of which platforms exist.
tenant_stores = Table(
    TENANT_STORES,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("platform", String(64), nullable=False),
    Column("base_url", Text, nullable=False),
    Column("credentials", Text, nullable=False),
    Column("wrapped_dek", Text, nullable=False),
    Column("status", String(32), nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # One connection per store, not per platform: sync/state.py already assumes
    # a tenant may run two shops, and two shops on the same software is the
    # ordinary case rather than the exotic one.
    UniqueConstraint("tenant_id", "platform", "base_url", name="uq_tenant_stores_tenant_store"),
)


#: The shop token NEURA made before the shop is connected (ADR-0052 §1).
#:
#: One per tenant: making another replaces it. Sealed exactly like a
#: connection's ``credentials`` (envelope encryption, security-model.md §5), so
#: a dump of this table alone is as useless as a dump of ``tenant_stores``.
#: *Connect* moves it into ``tenant_stores`` and deletes the row. **Nothing reads
#: it back to a screen**: it is shown once, by the request that made it.
shop_tokens = Table(
    SHOP_TOKENS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("credentials", Text, nullable=False),
    Column("wrapped_dek", Text, nullable=False),
    #: The console user who made it. A person, never a shopper.
    Column("made_by", String(64), nullable=False),
    Column("made_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


#: The secret the shop's server signs customer passes with (ADR-0057 §3). One
#: per tenant, sealed like the shop token: NEURA must use it to check a
#: signature, so a hash would not do.
customer_secrets = Table(
    CUSTOMER_SECRETS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("secret", Text, nullable=False),
    Column("wrapped_dek", Text, nullable=False),
    #: The console user who made it. A person, never a shopper.
    Column("made_by", String(64), nullable=False),
    Column("made_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


#: One run of the full check against a shop's bridge (ADR-0052 §4).
#:
#: Kept, rather than living only on a job row, because the job queue purges
#: finished work and the screen must still say *"19 of 19 · checked Sep 30"*.
#: ``store_id`` is ``NULL`` for a check made before the shop is connected, which
#: is also what *Connect* reads: it is allowed only after a clean check of the
#: same address. ``result`` holds the check's findings, never the token.
shop_checks = Table(
    SHOP_CHECKS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("store_id", String(64), nullable=True),
    Column("address", Text, nullable=False),
    #: ``pending`` until the worker writes ``done`` or ``failed``. A check that
    #: found problems is ``done``; ``failed`` means we could not run it.
    Column("status", String(16), nullable=False, server_default="pending"),
    Column("result", JSONB, nullable=True),
    Column("requested_by", String(64), nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Index("ix_shop_checks_tenant_requested", "tenant_id", "requested_at"),
)


#: What a tenant used, per day, per agent.
#:
#: A rollup rather than an event log: the row is created on first use and
#: incremented in place with ``ON CONFLICT DO UPDATE``, which is atomic in
#: PostgreSQL and therefore correct under concurrent turns without a lock the
#: application has to remember to take (ADR-0015).
tenant_usage = Table(
    TENANT_USAGE,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("usage_date", Date, primary_key=True),
    #: The agent this usage is attributable to — the "billed for CARE only"
    #: column in tenancy-and-packaging.md §3. Never an agent name known to this
    #: package; it arrives from the manifest of whatever agent ran.
    Column("agent_key", String(64), primary_key=True),
    Column("conversations", Integer, nullable=False, server_default="0"),
    Column("turns", Integer, nullable=False, server_default="0"),
    Column("llm_calls", Integer, nullable=False, server_default="0"),
    Column("tool_calls", Integer, nullable=False, server_default="0"),
    Column("escalations", Integer, nullable=False, server_default="0"),
    Column("blocked", Integer, nullable=False, server_default="0"),
    # BigInteger: a busy tenant passes two billion tokens in a year, and the
    # overflow would appear as a negative bill.
    Column("prompt_tokens", BigInteger, nullable=False, server_default="0"),
    Column("completion_tokens", BigInteger, nullable=False, server_default="0"),
    # Numeric, never float. Six decimal places because per-token pricing makes
    # a single call cost fractions of a cent, and rounding those to zero is how
    # a cost model quietly reports that inference is free.
    Column("cost_usd", Numeric(14, 6), nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # The budget check reads "everything this tenant spent today", across
    # agents. That is the hot query, so it is the index.
    Index("ix_tenant_usage_tenant_id_usage_date", "tenant_id", "usage_date"),
)
