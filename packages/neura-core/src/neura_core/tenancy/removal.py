"""Removing a shop: every row it owns, in every table, without naming one.

ADR-0061 §6 (refusing a shop from the admin dashboard) and ADR-0060 (refusing it
by command). ``scripts/widget_check.py``'s ``tenant_tables()`` is a hand-kept
list, and it fell behind once already (G76); it also names agents' tables, which
code the API runs may not do (AGENTS.md). This reads the list from the database
itself instead: **every base table with a ``tenant_id`` column**, the tables
that point at others deleted first.

**``audit_log`` is left, on purpose**: it is append-only by privilege, so a
shop's record outlives the shop (S10). The session is the shop's own tenant
session, so row-level security also keeps every delete inside that one shop.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.logging import get_logger

log = get_logger(__name__)

#: Kept, whatever happens to the shop (S10).
KEPT = frozenset({"audit_log"})

_TABLES = text(
    """
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = current_schema()
      AND c.column_name = 'tenant_id'
      AND t.table_type = 'BASE TABLE'
    ORDER BY c.table_name
    """
)

_REFERENCES = text(
    """
    SELECT child.relname AS child, parent.relname AS parent
    FROM pg_constraint k
    JOIN pg_class child ON child.oid = k.conrelid
    JOIN pg_class parent ON parent.oid = k.confrelid
    WHERE k.contype = 'f' AND k.connamespace = current_schema()::regnamespace
    """
)


async def remove_tenant(session: AsyncSession, tenant_id: str) -> dict[str, int]:
    """Delete the shop's rows from every table but the audit log. Rows per table."""
    tables = [str(t) for t in (await session.execute(_TABLES)).scalars() if t not in KEPT]
    points_at: dict[str, set[str]] = {table: set() for table in tables}
    for child, parent in (await session.execute(_REFERENCES)).all():
        if child in points_at and parent in points_at and child != parent:
            points_at[str(child)].add(str(parent))

    removed: dict[str, int] = {}
    for table in _children_first(points_at):
        # The name comes from the database's own catalogue, never from input.
        result = await session.execute(
            text(f'DELETE FROM "{table}" WHERE tenant_id = :tenant'),  # noqa: S608
            {"tenant": tenant_id},
        )
        removed[table] = int(getattr(result, "rowcount", 0) or 0)
    log.info("tenant_removed", tenant_id=tenant_id, rows=sum(removed.values()))
    return removed


def _children_first(points_at: dict[str, set[str]]) -> list[str]:
    """A table before every table it points at, so no delete breaks a reference."""
    pointed_at_by: dict[str, set[str]] = {table: set() for table in points_at}
    for child, parents in points_at.items():
        for parent in parents:
            pointed_at_by[parent].add(child)
    order: list[str] = []
    ready = sorted(t for t, children in pointed_at_by.items() if not children)
    waiting = {t: set(children) for t, children in pointed_at_by.items() if children}
    while ready:
        table = ready.pop(0)
        order.append(table)
        for parent in sorted(points_at[table]):
            children = waiting.get(parent)
            if children is None:
                continue
            children.discard(table)
            if not children:
                del waiting[parent]
                ready.append(parent)
                ready.sort()
    # A cycle (none exists) would leave tables here; delete them last rather
    # than skip them, and let the database say if a reference still holds.
    return order + sorted(waiting)


__all__ = ["KEPT", "remove_tenant"]
