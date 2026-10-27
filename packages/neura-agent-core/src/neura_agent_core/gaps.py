"""What shoppers asked that the shop's pages do not say — ADR-0064's data.

NEURA-GROW's nightly job reads the shop's chats and writes one row here per
reply that could not answer a fact the shop's pages could state (R38: handed
over, or answered only half). The console's *Missing from your pages* reads them
back grouped: one topic per product and label, counted by **different
conversations**, shown from two (R40), over the last 30 days, the most recent
question shown (R43).

**Here, in the shared core, and not in GROW's package**, for the reason Sold
out's data is not in SELL's: the page is the console's own, and the console may
not learn an agent's name (AGENTS.md, G88). Only GROW's job writes these rows,
so a shop without GROW has none, and its page is empty.

**What a row holds is derived from a shopper's words** (a short label and a
short question, both checked in code before they get here), so it goes with its
conversation: ``ConversationRepository.delete_older_than`` deletes a gap with
its chat, and shop removal knows all three tables (G76). The fixes record a
member of the shop's team, never a shopper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    Table,
    and_,
    distinct,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import metadata

PAGE_GAPS = "page_gaps"
PAGE_GAP_FIXES = "page_gap_fixes"
PAGE_GAP_SCANS = "page_gap_scans"

#: The page's window (ADR-0064 §3) and its threshold (R40).
GAP_DAYS = 30
MIN_SHOPPERS = 2

#: The longest label and question a row may hold. The job checks the shape
#: (grow.md §3); these are the columns' own limits behind it.
MAX_FACT_CHARS = 40
MAX_QUESTION_CHARS = 60
MAX_PRODUCT_ID_CHARS = 128


class GapKind(StrEnum):
    """How the reply failed the shopper (R38)."""

    #: The assistant handed the shopper over.
    HANDED_OVER = "handed_over"
    #: The assistant answered, but said it could not confirm something.
    HALF_ANSWERED = "half_answered"


#: One row per reply the job found a gap in. Keyed by the reply's own message
#: id, so a reply met twice is recorded once.
page_gaps = Table(
    PAGE_GAPS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("message_id", String(64), primary_key=True),
    Column("conversation_id", String(64), nullable=False),
    Column("kind", String(16), nullable=False),
    #: The product the reply looked at, or NULL for a fact about the shop.
    Column("product_id", String(MAX_PRODUCT_ID_CHARS), nullable=True),
    Column("fact", String(MAX_FACT_CHARS), nullable=False),
    Column("question", String(MAX_QUESTION_CHARS), nullable=False),
    #: When the shopper asked: the reply's own time, not the scan's.
    Column("asked_at", DateTime(timezone=True), nullable=False),
    Column("prompt_revision", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("kind IN ('handed_over', 'half_answered')", name="kind"),
    Index("ix_page_gaps_recent", "tenant_id", "asked_at"),
    Index("ix_page_gaps_conversation", "tenant_id", "conversation_id"),
)

#: *I added it*. Keyed by the topic: a product (``''`` for the shop) and label.
page_gap_fixes = Table(
    PAGE_GAP_FIXES,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("product_key", String(MAX_PRODUCT_ID_CHARS), primary_key=True),
    Column("fact", String(MAX_FACT_CHARS), primary_key=True),
    Column("fixed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    #: The member of the shop's team who pressed it.
    Column("fixed_by", String(64), nullable=False),
)

#: How far the nightly job has read each shop's chats.
page_gap_scans = Table(
    PAGE_GAP_SCANS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("scanned_until", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True, slots=True)
class PageGap:
    """One reply that could not answer a fact the shop's pages could state."""

    conversation_id: str
    message_id: str
    kind: GapKind
    product_id: str | None
    fact: str
    question: str
    asked_at: datetime
    prompt_revision: str | None = None


@dataclass(frozen=True, slots=True)
class GapTopic:
    """One row of the page: a question at least two shoppers asked."""

    product_id: str | None
    fact: str
    question: str
    shoppers: int
    last_asked: datetime


def _product_key(product_id: str | None) -> str:
    return product_id or ""


class PageGapRepository:
    """Every read and write of the three tables, under the shop's own RLS."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, tenant_id: str, gap: PageGap) -> bool:
        """Store one gap. False when this reply was already recorded."""
        result = await self._session.execute(
            pg_insert(page_gaps)
            .values(
                tenant_id=tenant_id,
                message_id=gap.message_id,
                conversation_id=gap.conversation_id,
                kind=gap.kind.value,
                product_id=gap.product_id,
                fact=gap.fact,
                question=gap.question,
                asked_at=gap.asked_at,
                prompt_revision=gap.prompt_revision,
            )
            .on_conflict_do_nothing(index_elements=[page_gaps.c.tenant_id, page_gaps.c.message_id])
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    def _topics_query(self, tenant_id: str, *, since: datetime, min_shoppers: int) -> Any:
        """Grouped by product and label; after *I added it*, only later gaps count."""
        fixes = page_gap_fixes
        joined = page_gaps.outerjoin(
            fixes,
            and_(
                fixes.c.tenant_id == page_gaps.c.tenant_id,
                fixes.c.product_key == func.coalesce(page_gaps.c.product_id, ""),
                fixes.c.fact == page_gaps.c.fact,
            ),
        )
        shoppers = func.count(distinct(page_gaps.c.conversation_id))
        last_asked = func.max(page_gaps.c.asked_at)
        latest_question = func.array_agg(
            aggregate_order_by(page_gaps.c.question, page_gaps.c.asked_at.desc()),
            type_=ARRAY(String),
        )[1]
        return (
            select(
                page_gaps.c.product_id,
                page_gaps.c.fact,
                latest_question.label("question"),
                shoppers.label("shoppers"),
                last_asked.label("last_asked"),
            )
            .select_from(joined)
            .where(
                page_gaps.c.tenant_id == tenant_id,
                page_gaps.c.asked_at >= since,
                or_(fixes.c.fixed_at.is_(None), page_gaps.c.asked_at > fixes.c.fixed_at),
            )
            .group_by(page_gaps.c.product_id, page_gaps.c.fact)
            .having(shoppers >= min_shoppers)
        )

    async def topics(
        self, tenant_id: str, *, since: datetime, min_shoppers: int = MIN_SHOPPERS
    ) -> list[GapTopic]:
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
            GapTopic(
                product_id=row.product_id,
                fact=row.fact,
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

    async def mark_fixed(
        self, tenant_id: str, *, product_id: str | None, fact: str, by: str
    ) -> None:
        """*I added it*: the topic leaves the page until shoppers ask it again."""
        statement = pg_insert(page_gap_fixes).values(
            tenant_id=tenant_id, product_key=_product_key(product_id), fact=fact, fixed_by=by
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    page_gap_fixes.c.tenant_id,
                    page_gap_fixes.c.product_key,
                    page_gap_fixes.c.fact,
                ],
                set_={"fixed_at": func.now(), "fixed_by": by},
            )
        )

    async def scanned_until(self, tenant_id: str) -> datetime | None:
        """How far the nightly job has read this shop's chats, if it ever has."""
        value = await self._session.scalar(
            select(page_gap_scans.c.scanned_until).where(page_gap_scans.c.tenant_id == tenant_id)
        )
        return cast("datetime | None", value)

    async def set_scanned_until(self, tenant_id: str, until: datetime) -> None:
        statement = pg_insert(page_gap_scans).values(tenant_id=tenant_id, scanned_until=until)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[page_gap_scans.c.tenant_id], set_={"scanned_until": until}
            )
        )


__all__ = [
    "GAP_DAYS",
    "MAX_FACT_CHARS",
    "MAX_PRODUCT_ID_CHARS",
    "MAX_QUESTION_CHARS",
    "MIN_SHOPPERS",
    "PAGE_GAPS",
    "PAGE_GAP_FIXES",
    "PAGE_GAP_SCANS",
    "GapKind",
    "GapTopic",
    "PageGap",
    "PageGapRepository",
    "page_gap_fixes",
    "page_gap_scans",
    "page_gaps",
]
