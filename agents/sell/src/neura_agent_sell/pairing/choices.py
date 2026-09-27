"""What the shop owner chose to suggest with a product — [ADR-0050].

**The owner's choice wins**, so the request path asks this first and, when a
choice exists, asks nothing else: no stored model pairing, no word search. An
empty choice means *show nothing for this product*; no choice at all means
automatic.

Split like ``cache.py``: a protocol ``orchestrate.py`` depends on, which a test
can satisfy with a dict, and one class against PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import delete
from sqlalchemy import select as sql_select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from neura_agent_sell.pairing.schema import sell_pairing_choices
from neura_core.db import Database

_CHOICES = sell_pairing_choices.c


@dataclass(frozen=True, slots=True)
class OwnerChoice:
    product_id: str
    #: In the owner's order. Empty means *show nothing*.
    chosen_ids: list[str]
    chosen_by: str
    chosen_at: datetime


@runtime_checkable
class OwnerChoices(Protocol):
    """The one question the request path asks."""

    async def get(self, product_id: str) -> list[str] | None:
        """The owner's list for this product, or ``None`` when there is none."""
        ...


class DatabaseOwnerChoices:
    """:class:`OwnerChoices` against PostgreSQL, for one tenant and one store.

    Every statement runs inside ``tenant_session``, so Row-Level Security keeps
    one merchant's choices off another's basket page.
    """

    def __init__(self, db: Database, *, tenant_id: str, store_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._store_id = store_id

    async def get(self, product_id: str) -> list[str] | None:
        async with self._db.tenant_session(self._tenant_id) as session:
            row = (
                await session.execute(
                    sql_select(_CHOICES.chosen_ids)
                    .where(_CHOICES.tenant_id == self._tenant_id)
                    .where(_CHOICES.store_id == self._store_id)
                    .where(_CHOICES.product_id == product_id)
                )
            ).first()
        return None if row is None else [str(i) for i in (row.chosen_ids or [])]

    async def for_products(self, product_ids: Sequence[str]) -> dict[str, OwnerChoice]:
        """Every choice among these products — one query for a page of the screen."""
        if not product_ids:
            return {}
        async with self._db.tenant_session(self._tenant_id) as session:
            rows = (
                await session.execute(
                    sql_select(sell_pairing_choices)
                    .where(_CHOICES.tenant_id == self._tenant_id)
                    .where(_CHOICES.store_id == self._store_id)
                    .where(_CHOICES.product_id.in_(list(product_ids)))
                )
            ).all()
        return {
            str(row.product_id): OwnerChoice(
                product_id=str(row.product_id),
                chosen_ids=[str(i) for i in (row.chosen_ids or [])],
                chosen_by=str(row.chosen_by),
                chosen_at=row.chosen_at,
            )
            for row in rows
        }

    async def choose(self, product_id: str, chosen_ids: Sequence[str], *, chosen_by: str) -> None:
        """Record the owner's list, replacing any earlier one. Validated by the caller."""
        values = {
            "tenant_id": self._tenant_id,
            "store_id": self._store_id,
            "product_id": product_id,
            "chosen_ids": list(chosen_ids),
            "chosen_by": chosen_by,
        }
        async with self._db.tenant_session(self._tenant_id) as session:
            statement = pg_insert(sell_pairing_choices).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[_CHOICES.tenant_id, _CHOICES.store_id, _CHOICES.product_id],
                    set_={
                        "chosen_ids": statement.excluded.chosen_ids,
                        "chosen_by": statement.excluded.chosen_by,
                        "chosen_at": statement.excluded.chosen_at,
                    },
                )
            )

    async def reset(self, product_id: str) -> bool:
        """Back to automatic. Returns whether there was a choice to remove."""
        async with self._db.tenant_session(self._tenant_id) as session:
            result = await session.execute(
                delete(sell_pairing_choices)
                .where(_CHOICES.tenant_id == self._tenant_id)
                .where(_CHOICES.store_id == self._store_id)
                .where(_CHOICES.product_id == product_id)
            )
        return bool(getattr(result, "rowcount", 0))


__all__ = ["DatabaseOwnerChoices", "OwnerChoice", "OwnerChoices"]
