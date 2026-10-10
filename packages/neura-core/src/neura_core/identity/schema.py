"""The three tables a *person* is made of. ADR-0026.

Every other table in this system describes a machine or a merchant. These
describe a human being, and they are the first ones to do so — which is why the
rule they follow is not quite the rule everything else follows.

## Two of these tables have no ``tenant_id``, and that is deliberate

Since 1.10 the convention has been absolute: every table carries a ``tenant_id``
under forced Row-Level Security ([ADR-0008]). ``users`` and ``login_tokens``
break it, for a reason that is structural rather than convenient:

> **At the moment somebody clicks a login link, we do not yet know which tenant
> they belong to. Finding that out is what the lookup is for.**

A tenant-scoped ``users`` table could only be read by a transaction that had
already set ``app.tenant_id``, which is the thing sign-in is trying to
establish. It is the same shape as the ``api_keys`` bootstrap problem that
[ADR-0014] solved with a hash-matched policy — and the same answer does not
work here, because a login token is redeemed *before* any session exists.

The exception is contained rather than waved through:

* ``users`` holds an email, a display name and timestamps. **No business data.**
  Leaking the whole table leaks a list of email addresses, not a single
  merchant's order, conversation or catalogue.
* ``login_tokens`` holds a hash, an expiry and a user id. Never a token.
* **``memberships`` is tenant-scoped and forced like everything else**, and it
  is the only route from a person to any merchant data. Tenant isolation is
  unchanged; what changed is that the door now has a doorman as well as a lock.

``tests/integration/test_migrations.py`` keys off the presence of a
``tenant_id`` column, so it protects ``memberships`` automatically and correctly
ignores the other two.

## Why there is no ``sessions`` table

A session is a signed cookie. There is no server-side session store to grow
without bound, to clean up, or to lose on a restart — and a signed cookie cannot
be forged without the secret.

**What that costs, and how it is paid:** a cookie cannot be revoked by deleting
a row. So *authorisation is re-derived from ``memberships`` on every request*
rather than baked into the cookie at sign-in. Removing somebody's access takes
effect on their next request, not at cookie expiry. A cookie that carried its
tenant would be an access grant nobody could withdraw.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT

from neura_core.db import metadata
from neura_core.identity.roles import Role

USERS = "users"
MEMBERSHIPS = "memberships"
LOGIN_TOKENS = "login_tokens"


#: One human. Not one merchant, and not one login — a person who owns two shops
#: is one row here and two rows in ``memberships``.
#:
#: ``email`` is ``CITEXT`` rather than ``String``, and that is a security
#: decision rather than a nicety. Addresses are case-insensitive in practice, so
#: ``Owner@shop.com`` and ``owner@shop.com`` are the same inbox — stored
#: case-sensitively they become two accounts, and the second one silently has no
#: access to the first one's shop. Lower-casing in Python instead would work
#: until one code path forgot.
users = Table(
    USERS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("email", CITEXT, nullable=False),
    Column("name", String(255), nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("email", name="uq_users_email"),
)


#: A person's access to one merchant. **The only route from a human to any
#: tenant's data**, and therefore the table that actually carries the
#: authorisation decision.
#:
#: ``role`` is one of three since ADR-0058 (``owner``, ``support``,
#: ``developer``; ADR-0026 §5 had one). What each may do is code
#: (``neura_core.identity.roles``), checked on every request; the database only
#: refuses a value the code does not know (``ck_memberships_role``), so a typo in
#: a script cannot make a role that quietly holds nothing. A membership made
#: without a role is an Owner, as every one made before roles existed is.
#:
#: ``revoked_at`` rather than a delete: who *used* to have access to a merchant's
#: conversations is exactly the question an incident asks, and a deleted row
#: cannot answer it.
memberships = Table(
    MEMBERSHIPS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("user_id", String(64), nullable=False),
    Column("role", String(32), nullable=False, server_default="owner"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(f"role IN ({', '.join(repr(r.value) for r in Role)})", name="role"),
    # One membership per person per tenant. Two would make "is this person
    # revoked?" a question with two answers, and the wrong one is the one that
    # grants access.
    UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    Index("ix_memberships_user_id", "user_id"),
)


#: A one-time sign-in link, in flight.
#:
#: **The token itself is never stored** — only its SHA-256, exactly as
#: ``api_keys.token_hash`` does, so a dump of this table cannot sign anyone in.
#:
#: ``consumed_at`` is set in the *same transaction* that creates the session, so
#: a link forwarded to a shared inbox cannot be redeemed twice. Checking then
#: writing in two steps would leave a window in which two requests both see an
#: unconsumed row.
#:
#: ``requested_ip`` is kept for abuse investigation and is deliberately **not**
#: compared at redemption: mail is routinely opened on a different network from
#: the one that asked for the link, and enforcing a match would lock out the
#: ordinary user while barely inconveniencing an attacker who already has the
#: link.
login_tokens = Table(
    LOGIN_TOKENS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("token_hash", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    Column("requested_ip", String(64), nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("token_hash", name="uq_login_tokens_token_hash"),
    Index("ix_login_tokens_user_id_created_at", "user_id", "created_at"),
)


__all__ = [
    "LOGIN_TOKENS",
    "MEMBERSHIPS",
    "USERS",
    "login_tokens",
    "memberships",
    "users",
]
