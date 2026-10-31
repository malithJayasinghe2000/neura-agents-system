"""Writing, counting and deleting observed events, for one tenant.

**No method here returns a session id, and none may.** The two reads that
return rows — :meth:`ObservedEventRepository.sold_out_demand` (ADR-0046 stage
1) and :meth:`ObservedEventRepository.rarely_added` (ADR-0071) — return
*counts* per product. A merchant is told how many sessions looked at a
sold-out jumper, never which ones: a session token on a screen is a tracking
identifier handed to a person, and nothing designed needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Float, and_, delete, distinct, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.observation.models import ObservedEvent, ObservedEventType
from neura_core.observation.schema import observed_events


@dataclass(frozen=True, slots=True)
class SoldOutDemand:
    """How much one product was wanted while it could not be bought."""

    product_id: str
    views: int
    #: Distinct session tokens. A session is one browsing visit, **not a
    #: person** — the screen says so.
    sessions: int
    last_viewed_at: datetime


#: ADR-0071 §1 (R75): a product is listed only when this many visitors opened
#: it in stock. A starting guess, measured against nothing.
RARELY_MIN_VISITORS = 10

#: ADR-0071 §1 (R79): *rarely* is fewer than 1 in this many of those visitors
#: adding it to the cart. Also a starting guess.
RARELY_ONE_IN = 10


@dataclass(frozen=True, slots=True)
class RarelyAdded:
    """An in-stock product many visitors opened and few added to the cart."""

    product_id: str
    #: Distinct sessions that opened it while it was in stock. A session is
    #: one browsing visit, **not a person**.
    visitors: int
    #: How many of those same sessions added it to the cart, so never more
    #: than ``visitors``.
    added: int
    last_viewed_at: datetime


class ObservedEventRepository:
    """The session is already tenant-scoped; RLS does the filtering."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, tenant_id: str, event: ObservedEvent) -> bool:
        """Store one event. Returns ``False`` if this event id was already stored.

        ``ON CONFLICT DO NOTHING`` because delivery is at least once: a retry of
        a delivery whose response was lost is the same page view, not a second.
        """
        result = await self._session.execute(
            pg_insert(observed_events)
            .values(
                tenant_id=tenant_id,
                event_id=event.event_id,
                session_id=event.session_id,
                event_type=event.type.value,
                product_id=event.product_id,
                occurred_at=event.occurred_at,
                in_stock=event.in_stock,
            )
            .on_conflict_do_nothing(
                index_elements=[observed_events.c.tenant_id, observed_events.c.event_id]
            )
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def delete_older_than(self, tenant_id: str, cutoff: datetime) -> int:
        """The retention sweep. Returns how many rows went."""
        result = await self._session.execute(
            delete(observed_events)
            .where(observed_events.c.tenant_id == tenant_id)
            .where(observed_events.c.occurred_at < cutoff)
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def delete_all(self, tenant_id: str) -> int:
        """Everything this tenant holds — the agreement was withdrawn.

        ADR-0042 §3's *removal on resolution*: without an agreement there is no
        reason to hold the rows, so they go rather than wait out the period.
        """
        result = await self._session.execute(
            delete(observed_events).where(observed_events.c.tenant_id == tenant_id)
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def any_for(self, tenant_id: str) -> bool:
        """Is anything left for a future sweep to delete?"""
        return bool(
            await self._session.scalar(
                select(exists().where(observed_events.c.tenant_id == tenant_id))
            )
        )

    async def sold_out_demand(
        self, tenant_id: str, *, since: datetime, limit: int = 100
    ) -> list[SoldOutDemand]:
        """Views of products that were sold out **when viewed**, per product.

        ADR-0046 stage 1, on ADR-0049's field. ``in_stock IS NULL`` is *unknown*
        and is deliberately not counted — a view nobody measured is not evidence
        that the product was sold out. Ordered by views for the merchant's
        reading; this order is never shown to, or used for, a shopper (0046 §6).
        """
        viewed = observed_events.c
        rows = (
            await self._session.execute(
                select(
                    viewed.product_id,
                    func.count().label("views"),
                    func.count(distinct(viewed.session_id)).label("sessions"),
                    func.max(viewed.occurred_at).label("last_viewed_at"),
                )
                .where(viewed.tenant_id == tenant_id)
                .where(viewed.event_type == ObservedEventType.PRODUCT_VIEWED.value)
                .where(viewed.in_stock.is_(False))
                .where(viewed.occurred_at >= since)
                .group_by(viewed.product_id)
                .order_by(func.count().desc(), viewed.product_id)
                .limit(limit)
            )
        ).all()
        return [
            SoldOutDemand(
                product_id=str(row.product_id),
                views=int(row.views),
                sessions=int(row.sessions),
                last_viewed_at=row.last_viewed_at,
            )
            for row in rows
        ]

    def _rarely_added_query(self, tenant_id: str, *, since: datetime, min_visitors: int) -> Any:
        """One row per qualifying product: visitors, how many of them added it, last view.

        A visitor is a session that viewed the product with ``in_stock`` true
        (ADR-0049; unknown stock is not counted, as on *Sold out*). *Added* is
        a ``cart.added`` from **one of those sessions**, so an add from a
        category page without opening the product does not count: the question
        is what the product's page does (ADR-0071 §1).
        """
        events = observed_events.c
        viewed = (
            select(
                events.product_id,
                events.session_id,
                func.max(events.occurred_at).label("last_viewed_at"),
            )
            .where(events.tenant_id == tenant_id)
            .where(events.event_type == ObservedEventType.PRODUCT_VIEWED.value)
            .where(events.in_stock.is_(True))
            .where(events.occurred_at >= since)
            .group_by(events.product_id, events.session_id)
            .subquery()
        )
        carted = (
            select(events.product_id, events.session_id)
            .where(events.tenant_id == tenant_id)
            .where(events.event_type == ObservedEventType.CART_ADDED.value)
            .where(events.occurred_at >= since)
            .distinct()
            .subquery()
        )
        visitors = func.count()
        added = func.count(carted.c.session_id)
        return (
            select(
                viewed.c.product_id,
                visitors.label("visitors"),
                added.label("added"),
                func.max(viewed.c.last_viewed_at).label("last_viewed_at"),
            )
            .select_from(
                viewed.outerjoin(
                    carted,
                    and_(
                        carted.c.product_id == viewed.c.product_id,
                        carted.c.session_id == viewed.c.session_id,
                    ),
                )
            )
            .group_by(viewed.c.product_id)
            .having(visitors >= min_visitors)
            .having(added * RARELY_ONE_IN < visitors)
        )

    async def rarely_added(
        self,
        tenant_id: str,
        *,
        since: datetime,
        min_visitors: int = RARELY_MIN_VISITORS,
        limit: int = 100,
    ) -> list[RarelyAdded]:
        """ADR-0071: the lowest share added first, then the most visitors.

        For the merchant's reading only; this order is never shown to, or used
        for, a shopper (ADR-0044 §8.2).
        """
        query = self._rarely_added_query(tenant_id, since=since, min_visitors=min_visitors)
        columns = query.selected_columns
        share = columns.added.cast(Float) / columns.visitors
        rows = (
            await self._session.execute(
                query.order_by(share, columns.visitors.desc(), columns.product_id).limit(limit)
            )
        ).all()
        return [
            RarelyAdded(
                product_id=str(row.product_id),
                visitors=int(row.visitors),
                added=int(row.added),
                last_viewed_at=row.last_viewed_at,
            )
            for row in rows
        ]

    async def count_rarely_added(
        self, tenant_id: str, *, since: datetime, min_visitors: int = RARELY_MIN_VISITORS
    ) -> int:
        """How many products the tab lists: Home's number is the tab's number."""
        query = self._rarely_added_query(tenant_id, since=since, min_visitors=min_visitors)
        return int(
            await self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        )

    async def any_views_since(self, tenant_id: str, *, since: datetime) -> bool:
        """Did the shop send any product view since ``since`` — sold out or not?

        The Sold out screen's *"Is it working?"* line. The switch that turns
        views on lives in the shop and cannot be seen from here (ADR-0044 §3);
        whether views arrive can, and it is what tells *switched off* apart from
        *nothing sold out was opened*. A yes or no, never a count: the screen
        shows demand for sold-out products and nothing else about traffic.
        """
        viewed = observed_events.c
        return bool(
            await self._session.scalar(
                select(
                    exists()
                    .where(viewed.tenant_id == tenant_id)
                    .where(viewed.event_type == ObservedEventType.PRODUCT_VIEWED.value)
                    .where(viewed.occurred_at >= since)
                )
            )
        )

    async def views_of_unknown_stock(self, tenant_id: str, *, since: datetime) -> int:
        """Views with no ``in_stock`` value, which the sold-out count leaves out."""
        viewed = observed_events.c
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(observed_events)
                .where(viewed.tenant_id == tenant_id)
                .where(viewed.event_type == ObservedEventType.PRODUCT_VIEWED.value)
                .where(viewed.in_stock.is_(None))
                .where(viewed.occurred_at >= since)
            )
            or 0
        )

    async def count_for(self, tenant_id: str) -> int:
        """How many rows are held. For the operator, never for a screen."""
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(observed_events)
                .where(observed_events.c.tenant_id == tenant_id)
            )
            or 0
        )


__all__ = ["ObservedEventRepository", "SoldOutDemand"]
