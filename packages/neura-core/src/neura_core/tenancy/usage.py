"""Usage metering — what a tenant consumed, per day, per agent.

**A rollup, not an event log** (ADR-0015). One row per
``(tenant, day, agent)``, created on first use and incremented in place. The
increment is a single ``INSERT … ON CONFLICT DO UPDATE SET x = x + excluded.x``,
which PostgreSQL performs atomically, so two turns finishing at the same instant
cannot lose a count and no application-level lock has to be remembered.

The alternative — an append-only event row per turn, aggregated on read — is
what a billing system eventually needs and is more than this needs now. It is
also strictly harder to add later than it is to keep the rollup correct, since
the rollup is what every reader wants anyway.

**Days are UTC.** A billing boundary that moves with a merchant's timezone is a
boundary two systems will disagree about; UTC is the only definition that stays
the same on both sides of an invoice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.tenancy.schema import tenant_usage

#: The counters that are summed. Kept as one list so a column added to the
#: schema and forgotten here fails loudly in tests rather than quietly under-
#: reporting a bill.
COUNTERS = (
    "conversations",
    "turns",
    "llm_calls",
    "tool_calls",
    "escalations",
    "blocked",
    "prompt_tokens",
    "completion_tokens",
)


def today() -> date:
    return datetime.now(UTC).date()


@dataclass(frozen=True, slots=True)
class UsageDelta:
    """What one turn consumed. Added to the day's row.

    Everything defaults to zero so a caller records only what it knows: the
    graph knows about escalations, the LLM client knows about tokens, and
    neither has to invent the other's numbers.
    """

    conversations: int = 0
    turns: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    escalations: int = 0
    blocked: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = Decimal("0")

    @property
    def is_empty(self) -> bool:
        return not any(getattr(self, name) for name in COUNTERS) and not self.cost_usd

    def __add__(self, other: UsageDelta) -> UsageDelta:
        return UsageDelta(
            **{name: getattr(self, name) + getattr(other, name) for name in COUNTERS},
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass(frozen=True, slots=True)
class UsageTotals:
    """What a tenant used over some period. The read side of the meter."""

    tenant_id: str
    conversations: int = 0
    turns: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    escalations: int = 0
    blocked: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = Decimal("0")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageMeter:
    """Records and reads usage. One instance per tenant-scoped session.

    Row-Level Security does the tenant filtering, so no method here writes a
    ``WHERE tenant_id`` for safety — only for the index. A meter constructed on
    a session for tenant A cannot read or write tenant B's row even if asked to
    (ADR-0008).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        tenant_id: str,
        agent_key: str,
        delta: UsageDelta,
        *,
        on: date | None = None,
    ) -> None:
        """Add one turn's consumption to today's row.

        Runs inside the caller's transaction on purpose, exactly as the audit
        log does: usage that was charged for work that then rolled back is a
        bill a merchant is right to dispute.
        """
        if delta.is_empty:
            return

        day = on or today()
        values = {
            "tenant_id": tenant_id,
            "usage_date": day,
            "agent_key": agent_key,
            "cost_usd": delta.cost_usd,
            **{name: getattr(delta, name) for name in COUNTERS},
        }

        statement = pg_insert(tenant_usage).values(**values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    tenant_usage.c.tenant_id,
                    tenant_usage.c.usage_date,
                    tenant_usage.c.agent_key,
                ],
                set_={
                    **{
                        name: tenant_usage.c[name] + getattr(statement.excluded, name)
                        for name in COUNTERS
                    },
                    "cost_usd": tenant_usage.c.cost_usd + statement.excluded.cost_usd,
                    "updated_at": func.now(),
                },
            )
        )

    async def totals(
        self,
        tenant_id: str,
        *,
        on: date | None = None,
        since: date | None = None,
        agent_key: str | None = None,
    ) -> UsageTotals:
        """Summed usage. ``on`` for one day, ``since`` for a period, neither for
        everything ever recorded."""
        columns = [func.coalesce(func.sum(tenant_usage.c[name]), 0) for name in COUNTERS]
        query = select(
            *columns,
            func.coalesce(func.sum(tenant_usage.c.cost_usd), Decimal("0")),
        ).where(tenant_usage.c.tenant_id == tenant_id)

        if on is not None:
            query = query.where(tenant_usage.c.usage_date == on)
        if since is not None:
            query = query.where(tenant_usage.c.usage_date >= since)
        if agent_key is not None:
            query = query.where(tenant_usage.c.agent_key == agent_key)

        row = (await self._session.execute(query)).one()
        counters = dict(zip(COUNTERS, (int(value) for value in row[:-1]), strict=True))
        return UsageTotals(tenant_id=tenant_id, **counters, cost_usd=Decimal(row[-1]))

    async def spend_today(self, tenant_id: str, *, on: date | None = None) -> Decimal:
        """The number the budget ladder is measured against."""
        totals = await self.totals(tenant_id, on=on or today())
        return totals.cost_usd

    async def by_agent(self, tenant_id: str, *, on: date | None = None) -> dict[str, UsageTotals]:
        """Per-agent breakdown for one day — "billed for CARE only" made
        checkable (tenancy-and-packaging.md §3)."""
        query = (
            select(
                tenant_usage.c.agent_key,
                *(tenant_usage.c[name] for name in COUNTERS),
                tenant_usage.c.cost_usd,
            )
            .where(tenant_usage.c.tenant_id == tenant_id)
            .where(tenant_usage.c.usage_date == (on or today()))
            .order_by(tenant_usage.c.agent_key)
        )
        rows = (await self._session.execute(query)).all()
        return {
            row[0]: UsageTotals(
                tenant_id=tenant_id,
                **dict(zip(COUNTERS, (int(v) for v in row[1:-1]), strict=True)),
                cost_usd=Decimal(row[-1]),
            )
            for row in rows
        }

    async def by_agent_since(
        self, tenant_id: str, *, since: date | None = None
    ) -> dict[str, UsageTotals]:
        """Per-agent totals over a period — ``since`` a day, or everything.

        The rollup's grain is ``(tenant, day, agent)``, so this is the same sum
        :meth:`totals` does, grouped by agent: the rows for one agent over the
        period add up to that agent's figure, and every agent's figure adds up
        to the period's total. The Usage screen shows it for the period chosen
        (console.md §3.5, 2026-09-28) rather than for today only.
        """
        query = (
            select(
                tenant_usage.c.agent_key,
                *(func.sum(tenant_usage.c[name]) for name in COUNTERS),
                func.sum(tenant_usage.c.cost_usd),
            )
            .where(tenant_usage.c.tenant_id == tenant_id)
            .group_by(tenant_usage.c.agent_key)
            .order_by(tenant_usage.c.agent_key)
        )
        if since is not None:
            query = query.where(tenant_usage.c.usage_date >= since)
        rows = (await self._session.execute(query)).all()
        return {
            row[0]: UsageTotals(
                tenant_id=tenant_id,
                **dict(zip(COUNTERS, (int(v or 0) for v in row[1:-1]), strict=True)),
                cost_usd=Decimal(row[-1] or 0),
            )
            for row in rows
        }

    async def worked_without_a_conversation(
        self, tenant_id: str, *, since: date | None = None
    ) -> bool:
        """Did an agent call a model on a day it served no turn, in the period?

        Background work — a pairing computed off the request path (ADR-0045) —
        records model calls and no turn, so the Usage screen can show AI use on
        a day nobody chatted and must say why. A day that mixed both is not
        detected: the rollup cannot split it, so this errs towards saying
        nothing rather than guessing.
        """
        rows = (
            select(tenant_usage.c.agent_key)
            .where(tenant_usage.c.tenant_id == tenant_id)
            .where(tenant_usage.c.turns == 0)
            .where(tenant_usage.c.llm_calls > 0)
        )
        if since is not None:
            rows = rows.where(tenant_usage.c.usage_date >= since)
        return bool(await self._session.scalar(select(rows.exists())))

    async def first_recorded(self, tenant_id: str) -> date | None:
        """The first day anything was recorded — what "everything" starts from."""
        first: date | None = await self._session.scalar(
            select(func.min(tenant_usage.c.usage_date)).where(tenant_usage.c.tenant_id == tenant_id)
        )
        return first
