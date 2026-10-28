"""What shoppers asked for that the shop does not sell — ADR-0068's data.

NEURA-GROW's nightly job reads the shop's chats and writes one row here per
reply that said the shop does not have a kind of product the shopper asked for
(R64: *"Do you have matcha?"*). The console's *Shoppers asked for* reads them
back grouped: one row per label, counted by **different conversations**, shown
from two (ADR-0068 §3), over the last 30 days, the most recent question shown.

**Here, in the shared core, beside** :mod:`neura_agent_core.gaps`, for the same
reason: the page is the console's own, and the console may not learn an agent's
name (AGENTS.md, G88). Only GROW's job writes these rows.

**What a row holds is derived from a shopper's words** (a short label and a
short question, checked in code by the same rules as a gap's), so it goes with
its conversation: ``ConversationRepository.delete_older_than`` deletes it with
its chat, and shop removal knows both tables (G76). *Hide* records a member of
the shop's team, never a shopper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Column, DateTime, Index, String, Table, and_, distinct, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from neura_agent_core.gaps import MAX_FACT_CHARS, MAX_QUESTION_CHARS, MIN_SHOPPERS
from neura_core import metadata

WANTED_ITEMS = "wanted_items"
WANTED_HIDES = "wanted_hides"

#: A label is checked exactly as a gap's topic is (ADR-0068 §6), so it has the
#: same limit.
MAX_LABEL_CHARS = MAX_FACT_CHARS

#: One row per reply that said the shop does not have it. Keyed by the reply's
#: own message id, so a reply met twice is recorded once.
wanted_items = Table(
    WANTED_ITEMS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("message_id", String(64), primary_key=True),
    Column("conversation_id", String(64), nullable=False),
    Column("label", String(MAX_LABEL_CHARS), nullable=False),
    Column("question", String(MAX_QUESTION_CHARS), nullable=False),
    #: When the shopper asked: the reply's own time, not the scan's.
    Column("asked_at", DateTime(timezone=True), nullable=False),
    Column("prompt_revision", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_wanted_items_recent", "tenant_id", "asked_at"),
    Index("ix_wanted_items_conversation", "tenant_id", "conversation_id"),
)

#: *Hide*, by label (R62).
wanted_hides = Table(
    WANTED_HIDES,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("label", String(MAX_LABEL_CHARS), primary_key=True),
    Column("hidden_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    #: The member of the shop's team who pressed it.
    Column("hidden_by", String(64), nullable=False),
)


@dataclass(frozen=True, slots=True)
class WantedItem:
    """One reply that said the shop does not have what the shopper asked for."""

    conversation_id: str
    message_id: str
    label: str
    question: str
    asked_at: datetime
    prompt_revision: str | None = None


@dataclass(frozen=True, slots=True)
class WantedTopic:
    """One row of the page: a thing at least two shoppers asked for."""

    label: str
    question: str
    shoppers: int
    last_asked: datetime


def counted_since_hide() -> Any:
    """A row counts if its label was never hidden, or was asked for after *Hide*.

    The same clause the page and *See the chats* use, so the chats listed are
    exactly the chats counted.
    """
    hidden_at = (
        select(wanted_hides.c.hidden_at)
        .where(
            wanted_hides.c.tenant_id == wanted_items.c.tenant_id,
            wanted_hides.c.label == wanted_items.c.label,
        )
        .scalar_subquery()
    )
    return or_(hidden_at.is_(None), wanted_items.c.asked_at > hidden_at)


class WantedRepository:
    """Every read and write of the two tables, under the shop's own RLS."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, tenant_id: str, item: WantedItem) -> bool:
        """Store one row. False when this reply was already recorded."""
        result = await self._session.execute(
            pg_insert(wanted_items)
            .values(
                tenant_id=tenant_id,
                message_id=item.message_id,
                conversation_id=item.conversation_id,
                label=item.label,
                question=item.question,
                asked_at=item.asked_at,
                prompt_revision=item.prompt_revision,
            )
            .on_conflict_do_nothing(
                index_elements=[wanted_items.c.tenant_id, wanted_items.c.message_id]
            )
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    def _topics_query(self, tenant_id: str, *, since: datetime, min_shoppers: int) -> Any:
        """Grouped by label; after *Hide*, only later asks count."""
        shoppers = func.count(distinct(wanted_items.c.conversation_id))
        last_asked = func.max(wanted_items.c.asked_at)
        latest_question = func.array_agg(
            aggregate_order_by(wanted_items.c.question, wanted_items.c.asked_at.desc()),
            type_=ARRAY(String),
        )[1]
        return (
            select(
                wanted_items.c.label,
                latest_question.label("question"),
                shoppers.label("shoppers"),
                last_asked.label("last_asked"),
            )
            .where(
                and_(
                    wanted_items.c.tenant_id == tenant_id,
                    wanted_items.c.asked_at >= since,
                    counted_since_hide(),
                )
            )
            .group_by(wanted_items.c.label)
            .having(shoppers >= min_shoppers)
        )

    async def topics(
        self, tenant_id: str, *, since: datetime, min_shoppers: int = MIN_SHOPPERS
    ) -> list[WantedTopic]:
        """The page's rows: most asked first, then the most recent."""
        query = self._topics_query(tenant_id, since=since, min_shoppers=min_shoppers)
        rows = (
            await self._session.execute(
                query.order_by(
                    query.selected_columns.shoppers.desc(),
                    query.selected_columns.last_asked.desc(),
                )
            )
        ).all()
        return [
            WantedTopic(
                label=row.label,
                question=row.question,
                shoppers=int(row.shoppers),
                last_asked=row.last_asked,
            )
            for row in rows
        ]

    async def count_topics(
        self, tenant_id: str, *, since: datetime, min_shoppers: int = MIN_SHOPPERS
    ) -> int:
        """How many rows the page shows: Home's number is the page's number."""
        query = self._topics_query(tenant_id, since=since, min_shoppers=min_shoppers)
        return int(
            await self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        )

    async def labels_since(self, tenant_id: str, *, since: datetime) -> list[str]:
        """Every label stored in the window, for the model to reuse (ADR-0068 §6)."""
        rows = await self._session.scalars(
            select(wanted_items.c.label)
            .where(wanted_items.c.tenant_id == tenant_id, wanted_items.c.asked_at >= since)
            .distinct()
            .order_by(wanted_items.c.label)
        )
        return list(rows)

    async def hide(self, tenant_id: str, *, label: str, by: str) -> None:
        """*Hide*: the thing leaves the page until shoppers ask for it again."""
        statement = pg_insert(wanted_hides).values(tenant_id=tenant_id, label=label, hidden_by=by)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[wanted_hides.c.tenant_id, wanted_hides.c.label],
                set_={"hidden_at": func.now(), "hidden_by": by},
            )
        )


__all__ = [
    "MAX_LABEL_CHARS",
    "WANTED_HIDES",
    "WANTED_ITEMS",
    "WantedItem",
    "WantedRepository",
    "WantedTopic",
    "counted_since_hide",
    "wanted_hides",
    "wanted_items",
]
