"""Booking an agent's daily job, without naming the agent. ADR-0064, piece 1c.

An agent with background work that runs once a day says so in its manifest
(``daily_job = "<job kind>"``). GROW is the first: its night check reads the
shop's chats (*Missing from your pages*). The API may not learn an agent's name
(AGENTS.md), so it books whatever job kinds the installed manifests declare, for
the agents a shop has, **the first time that shop has a chat to read**: called
where a new conversation books the retention sweep, in the same transaction.

The job then books itself again each day while the shop still has the agent.
A booking while one is live is a no-op (the queue's dedupe key), so every new
chat may call this.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

from neura_api.registry import discover_agents
from neura_core.jobs import JobQueue
from neura_core.tenancy import TenantRepository

#: The first run is a day after the first chat, then every day.
DAILY = timedelta(days=1)


@cache
def daily_jobs() -> dict[str, str]:
    """Agent key to the job kind its manifest declares, for every installed agent."""
    return {
        key: kind
        for key, discovered in discover_agents().items()
        if isinstance(kind := getattr(discovered.manifest, "daily_job", None), str) and kind
    }


async def book_daily_jobs(
    session: Any, tenant_id: str, *, now: datetime | None = None
) -> list[str]:
    """Book each daily job this shop's agents declare. Returns the kinds booked."""
    jobs = daily_jobs()
    if not jobs:
        return []
    tenant = await TenantRepository(session).get(tenant_id)
    if tenant is None:
        return []
    booked: list[str] = []
    for key, kind in sorted(jobs.items()):
        if not tenant.may_use(key):
            continue
        await JobQueue(session).enqueue(
            tenant_id,
            kind,
            dedupe_key=kind,
            run_after=(now or datetime.now(UTC)) + DAILY,
        )
        booked.append(kind)
    return booked


__all__ = ["DAILY", "book_daily_jobs", "daily_jobs"]
