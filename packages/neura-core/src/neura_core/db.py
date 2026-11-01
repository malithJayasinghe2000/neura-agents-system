"""The database seam — engine, sessions, and tenant scoping.

Lives here, at the bottom of the graph, because every persistence layer above it
needs the same two things: a pooled async engine, and a transaction that has
told PostgreSQL which tenant it is acting for. Putting it in one of the upper
packages would mean the next one to need it either imports sideways or writes a
second copy.

**The one rule: there is no un-scoped session.** :func:`Database.tenant_session`
is the only way to get one, and it issues ``set_config('app.tenant_id', …,
true)`` before handing it over. Row-Level Security policies read that setting,
so a transaction that never set it sees nothing at all
(docs/architecture/adr/0008-multi-tenancy-rls.md).

``true`` there means *transaction-local*: the setting is discarded at commit or
rollback. That is deliberate and it is the reason connection pooling is safe —
a pooled connection cannot carry one tenant's identity into the next request's
transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from neura_core.config import get_settings
from neura_core.errors import ConfigurationError
from neura_core.logging import get_logger

log = get_logger(__name__)

#: The session variable every RLS policy reads.
TENANT_SETTING = "app.tenant_id"

#: The session variable that lets *one* row of ``api_keys`` be read before the
#: tenant is known. See :meth:`Database.credential_session` and ADR-0014.
CREDENTIAL_SETTING = "app.api_key_hash"

#: The person a transaction is acting as, for the sign-in bootstrap only
#: (ADR-0026). Read by the ``membership_lookup`` policy on ``memberships``.
#: **Never a substitute for** ``app.tenant_id`` — it grants sight of which
#: tenants a person belongs to, and nothing belonging to any of them.
USER_SETTING = "app.user_id"

#: Predictable constraint and index names. Without this, Alembic autogenerate
#: emits migrations that cannot drop an unnamed constraint, and a schema becomes
#: hard to change some months after nobody remembers why.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: Every table in the system registers here. Alembic diffs against it, so a
#: table defined in a package that ``infra/migrations/env.py`` does not import
#: is a table Alembic will offer to drop.
metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    """A pooled async engine plus tenant-scoped sessions."""

    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 5,
        echo: bool = False,
    ) -> None:
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            echo=echo,
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls) -> Database:
        settings = get_settings()
        return cls(
            str(settings.database_url),
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def tenant_session(self, tenant_id: str) -> AsyncIterator[AsyncSession]:
        """A transaction scoped to one tenant. Commits on exit, rolls back on error.

        Rejects an empty tenant id rather than issuing an unscoped transaction.
        An empty string would set the GUC to ``''``, which matches no row — so
        the query would return nothing and look like missing data instead of the
        programming error it is.
        """
        if not tenant_id:
            raise ConfigurationError(
                "tenant_session requires a tenant_id. Every row in this database "
                "belongs to a tenant, and an unscoped transaction sees none of them.",
            )

        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": TENANT_SETTING, "value": tenant_id},
            )
            yield session

    @asynccontextmanager
    async def credential_session(self, token_hash: str) -> AsyncIterator[AsyncSession]:
        """The one transaction that is allowed to run before the tenant is known.

        Authentication is a chicken-and-egg problem under ADR-0008: the tenant
        comes *from* the API key, so the row that identifies the tenant has to
        be read by a transaction that cannot yet say which tenant it is acting
        for — and such a transaction sees nothing, which is the whole point of
        the design.

        The answer is not an exemption. This session sets
        ``app.api_key_hash`` and **not** ``app.tenant_id``, and the policy on
        ``api_keys`` grants read access to rows whose hash equals that setting.
        So the caller may read exactly the row for a credential they already
        hold, and nothing else in the database — no other key, no tenant, no
        conversation. Presenting a key you possess to learn about that key
        discloses nothing you did not already have (ADR-0014).

        ``READ ONLY`` makes it structural rather than careful: the bootstrap
        path cannot write, so it cannot become a way to mutate anything before
        authentication has happened.
        """
        if not token_hash:
            raise ConfigurationError(
                "credential_session requires a token hash. Without one the "
                "session can read nothing, which would look like an unknown "
                "API key rather than the programming error it is.",
            )

        async with self._sessions() as session, session.begin():
            # First statement in the transaction, or PostgreSQL rejects it.
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": CREDENTIAL_SETTING, "value": token_hash},
            )
            yield session

    @asynccontextmanager
    async def identity_session(self, user_id: str = "") -> AsyncIterator[AsyncSession]:
        """Sign-in, before any tenant is known (ADR-0026).

        The third chicken-and-egg in this design, and the sharpest one. A person
        clicking a login link has not yet told us which merchant they act for —
        working that out is the entire purpose of the request. So this
        transaction sets **no** ``app.tenant_id`` and every tenant-scoped table
        returns nothing to it.

        What it can reach is deliberately tiny:

        * ``users`` and ``login_tokens``, which carry no ``tenant_id`` and hold
          no business data — an email, a display name, a token *hash*.
        * once ``user_id`` is supplied, the caller's own rows in ``memberships``,
          via the ``membership_lookup`` policy. That is the answer to *"which
          merchants may this person act for?"* and it is the last thing this
          session is for. Every subsequent read opens an ordinary
          :meth:`tenant_session` for one of the ids it returned.

        **``user_id`` is passed only after it has been proved** — by redeeming a
        one-time token or by verifying a signed session cookie. Passing an
        unverified id here is the mistake this whole design exists to prevent,
        and it would be indistinguishable from working (`AGENTS.md` rule 3).

        Not ``READ ONLY``, unlike the other two bootstrap sessions, and the
        reason is specific: redeeming a login token must **mark it consumed in
        the same transaction that reads it**, or two requests from a forwarded
        link both see an unconsumed row and both sign in.
        """
        async with self._sessions() as session, session.begin():
            if user_id:
                await session.execute(
                    text("SELECT set_config(:name, :value, true)"),
                    {"name": USER_SETTING, "value": user_id},
                )
            yield session

    @asynccontextmanager
    async def dispatch_session(self) -> AsyncIterator[AsyncSession]:
        """The transaction a background worker uses to find out *whom* to work for.

        The second chicken-and-egg in this design, and the same answer as the
        first. Background work has no request and no credential, so it cannot
        name a tenant — and a transaction that names no tenant sees nothing,
        which is the whole point of ADR-0008. A sweeper therefore has no way to
        ask "which rows across every tenant are due?".

        This session sets **no** ``app.tenant_id``, so every policy-protected
        table returns nothing to it. The one useful statement it can make is
        ``neura_due_tenants()`` — a ``SECURITY DEFINER`` function owned by a
        ``NOLOGIN`` role, holding a column grant that excludes ``payload``, and
        returning a list of tenant ids and nothing else. The caller then opens an
        ordinary :meth:`tenant_session` for each id it was given
        (docs/architecture/adr/0022-scheduling-under-rls.md).

        ``READ ONLY`` makes that structural rather than careful: dispatch cannot
        become a way to mutate anything before a tenant has been named.
        """
        async with self._sessions() as session, session.begin():
            # First statement in the transaction, or PostgreSQL rejects it.
            await session.execute(text("SET TRANSACTION READ ONLY"))
            yield session

    @asynccontextmanager
    async def follow_session(self) -> AsyncIterator[AsyncSession]:
        """The transaction a tap on a counted link runs in (ADR-0074 §7).

        The third chicken-and-egg, answered the way the first two were. A tap
        on ``/go/<code>`` carries a code and nothing else, so the shop is not
        known until the link is found. This session sets **no**
        ``app.tenant_id`` and sees nothing; the one useful statement it can make
        is ``neura_follow_link()``, a ``SECURITY DEFINER`` function owned by a
        ``NOLOGIN`` role, which adds 1 to that link's day and returns the
        address to send the shopper to, and nothing else.

        **Not** ``READ ONLY``, unlike :meth:`dispatch_session`: counting the
        click is a write, and the function is the only thing here that can make
        one.
        """
        async with self._sessions() as session, session.begin():
            yield session

    async def assert_isolation_applies(self) -> None:
        """Verify that Row-Level Security actually applies to this connection.

        PostgreSQL exempts superusers and ``BYPASSRLS`` roles from every policy.
        Connect as one and tenant isolation is off — with no error, no warning,
        and every test that "proves" isolation quietly passing because it is
        testing a policy that was never consulted. That is the most expensive
        silent failure in the system, and it is one query to rule out.

        Called from :meth:`ping`, so ``/v1/health/ready`` fails rather than a
        deployment serving traffic with isolation disabled.
        """
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT current_user, rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()

        user, is_super, bypasses = row
        if is_super or bypasses:
            raise ConfigurationError(
                f"Refusing to run: the database role {user!r} is "
                f"{'a superuser' if is_super else 'BYPASSRLS'}, so Row-Level "
                "Security does not apply to it and tenant isolation is silently "
                "disabled. Point DATABASE_URL at the unprivileged application "
                "role (docs/architecture/adr/0008-multi-tenancy-rls.md).",
                details={"role": user, "superuser": is_super, "bypassrls": bypasses},
            )

    async def ping(self) -> bool:
        """Reachability *and* isolation check, for ``/v1/health/ready``."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await self.assert_isolation_applies()
        except ConfigurationError:
            raise
        except Exception as exc:
            log.warning("database_unreachable", error=str(exc))
            return False
        return True

    async def dispose(self) -> None:
        await self._engine.dispose()


@lru_cache(maxsize=1)
def get_database() -> Database:
    """Process-wide database. One pool, created on first use."""
    return Database.from_settings()
