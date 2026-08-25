"""The one read in this system that crosses a tenant boundary.

Under [ADR-0008](../../../../docs/architecture/adr/0008-multi-tenancy-rls.md) no
transaction can enumerate tenants: a session that has not set ``app.tenant_id``
matches no row in any policy-protected table. That is the property, not a
limitation to route around — and it leaves background work with a question no
transaction can ask: *whose work is due?*

**A job table with a ``tenant_id`` column does not answer it.** ``job_queue`` is
under the same policy as the other sixteen tables, so it makes the data safe and
leaves the dispatch exactly as impossible. The answer has two halves, and this
file is the second one.

``neura_due_tenants(as_of)`` is a ``SECURITY DEFINER`` function owned by
``neura_scheduler`` — a role with no ``LOGIN`` and no ``BYPASSRLS``, holding a
column-level grant that excludes ``payload``. It returns ``SETOF text``: a list
of tenant ids, and nothing else. Everything after this call happens in an
ordinary ``tenant_session``.

The exemption is real and is stated rather than buried: a role exists that can
see, for every tenant, that a job is pending and when. Tenant ids and timing —
no payload, no conversation, no key. That is the entire blast radius, and
[ADR-0022](../../../../docs/architecture/adr/0022-scheduling-under-rls.md)
compares it against the two alternatives it was chosen over.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from neura_core.jobs.schema import DUE_TENANTS_FUNCTION

if TYPE_CHECKING:  # pragma: no cover
    from neura_core.db import Database

#: The call, written once. Parameterised — never interpolated — even though the
#: only argument is a timestamp the caller controls, because a dispatch function
#: is exactly the place a future maintainer would be tempted to add a filter
#: built from a string.
_DUE_TENANTS_SQL = text(f"SELECT {DUE_TENANTS_FUNCTION}(:as_of)")


async def due_tenants(db: Database, *, now: datetime | None = None) -> list[str]:
    """Which tenants have a job due, as of ``now``.

    Runs in :meth:`neura_core.db.Database.dispatch_session` — read-only, and
    with no ``app.tenant_id`` set, so every *table* query from that transaction
    returns nothing. The function call is the only statement in it that can
    answer anything, which is what makes this narrow by construction rather than
    by discipline.

    Sorted so that a sweep is reproducible and a log of two consecutive polls can
    be diffed by eye.
    """
    moment = now or datetime.now(UTC)
    async with db.dispatch_session() as session:
        rows = (await session.execute(_DUE_TENANTS_SQL, {"as_of": moment})).scalars().all()
    return sorted(str(row) for row in rows if row)


__all__ = ["due_tenants"]
