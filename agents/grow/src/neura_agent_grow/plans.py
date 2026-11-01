"""The calendar step of GROW's night run: a plan for each kept date. ADR-0072 §5.

Once a night, for one shop: every kept date **21 days away or closer** that has
no plan yet gets one (R87). A date added or kept late, already closer than 21
days, gets its plan on the next run rather than never (ADR-0073). *Make it
again* is answered here too, by the same step, run at once on its own job
(:mod:`neura_agent_grow.jobs`).

**One call per plan, two when the first answer is refused**
(:func:`neura_agent_grow.campaign.write_plan`). A plan refused twice is stored
as *could not be made* and is not tried again by itself: the page offers *Make
it again*, so a date never costs more than two calls a night unasked.

**What the model is given** comes from the shared core, never from a chat: the
synced catalogue (up to 100 products in stock; **or exactly the products the
owner chose for the plan**, sold out or not, D20), and the labels and counts on
*Shoppers asked for* and *Missing from your pages*, with the same 30 days and
2-shopper rule as those pages (a thing the owner hid stays out).

A provider outage **stops the step** where it is (the queue retries the run);
every plan made before it is already stored.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from neura_agent_core.calendar import (
    PLAN_DAYS_BEFORE,
    CalendarRepository,
    in_stock,
    kept_occurrences,
    shop_today,
)
from neura_agent_core.gaps import GAP_DAYS, PageGapRepository
from neura_agent_core.wanted import WantedRepository
from neura_agent_grow.campaign import (
    MAX_FACTS,
    MAX_PRODUCTS,
    CatalogueItem,
    Fact,
    PlanInput,
    write_plan,
)
from neura_commerce.sync.schema import synced_entities
from neura_core import get_logger
from neura_core.tenancy import TenantRepository

log = get_logger(__name__)

#: The most plans one run makes. A shop with more due is finished the next night.
MAX_PLANS_PER_RUN = 20
#: How many synced products are read to find the 100 in stock.
_READ_PRODUCTS = 5000

#: Called in the transaction that stored a plan: books the retention sweep.
AfterStore = Callable[[Any, str], Awaitable[Any]]


@dataclass(slots=True)
class PlansResult:
    made: int = 0
    failed: int = 0
    calls: int = 0
    #: Why the step stopped early, if it did: ``"provider"`` (unreachable).
    stopped: str = ""

    def summary(self) -> str:
        line = f"{self.made} plan(s) made · {self.failed} could not be made"
        return line + (f" · stopped: {self.stopped}" if self.stopped else "")


@dataclass(frozen=True, slots=True)
class _Work:
    date_key: str
    day: date
    name: str
    #: The owner's products for this plan (D20), or ``None``: the AI chooses.
    chosen: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Catalogue:
    """What the night run reads of the synced catalogue, once per shop."""

    #: Up to 100 products in stock, by title: what the AI chooses from.
    stocked: list[CatalogueItem]
    #: More than 100 were in stock.
    cut: bool
    #: Every product with a title, in stock or not, by id: the owner's choices
    #: are found here (R126), and a gap's product is named from it.
    every: dict[str, CatalogueItem]

    @property
    def titles(self) -> dict[str, str]:
        return {product_id: item.title for product_id, item in self.every.items()}


async def catalogue(session: Any, tenant_id: str) -> Catalogue:
    """Up to 100 products in stock, by title; whether more were cut; every product."""
    entities = synced_entities.c
    rows = (
        await session.execute(
            select(entities.external_id, entities.entity_type, entities.document)
            .where(entities.tenant_id == tenant_id)
            .where(entities.entity_type.in_(("product", "category")))
            .order_by(entities.external_id)
            .limit(_READ_PRODUCTS)
        )
    ).all()
    names = {
        str(row.external_id): str((row.document or {}).get("name") or "")
        for row in rows
        if row.entity_type == "category"
    }
    every: dict[str, CatalogueItem] = {}
    stocked: list[CatalogueItem] = []
    for row in rows:
        if row.entity_type != "product":
            continue
        document = row.document or {}
        title = str(document.get("title") or "").strip()
        if not title:
            continue
        categories = [str(c) for c in document.get("category_ids") or []]
        item = CatalogueItem(
            id=str(row.external_id),
            title=title,
            category=next((names[c] for c in categories if names.get(c)), ""),
        )
        every[item.id] = item
        if in_stock(document):
            stocked.append(item)
    stocked.sort(key=lambda item: (item.title.lower(), item.id))
    return Catalogue(stocked=stocked[:MAX_PRODUCTS], cut=len(stocked) > MAX_PRODUCTS, every=every)


async def facts(
    session: Any, tenant_id: str, *, now: datetime, titles: Mapping[str, str]
) -> list[Fact]:
    """The labels and counts on the two GROW pages: never a shopper's question."""
    since = now - timedelta(days=GAP_DAYS)
    wanted = (await WantedRepository(session).topics(tenant_id, since=since))[:MAX_FACTS]
    gaps = (await PageGapRepository(session).topics(tenant_id, since=since))[:MAX_FACTS]
    return [
        Fact(ref=f"w{n}", kind="wanted", label=topic.label, shoppers=topic.shoppers)
        for n, topic in enumerate(wanted, 1)
    ] + [
        Fact(
            ref=f"g{n}",
            kind="gap",
            label=topic.fact,
            shoppers=topic.shoppers,
            product_id=topic.product_id,
            product_title=titles.get(topic.product_id or "", ""),
        )
        for n, topic in enumerate(gaps, 1)
    ]


async def make_plans(
    db: Any,
    tenant_id: str,
    *,
    llm: object,
    prompt: str,
    prompt_revision: str,
    now: datetime,
    asked_only: bool = False,
    after_store: AfterStore | None = None,
) -> PlansResult:
    """One run of the calendar step for one shop. Raises nothing for an outage.

    ``asked_only``: answer *Make it again* and nothing else (the job run at once).
    """
    result = PlansResult()
    async with db.tenant_session(tenant_id) as session:
        repository = CalendarRepository(session)
        country = await repository.country(tenant_id)
        today = shop_today(country, now)
        work: list[_Work] = []
        for plan in await repository.asked_again(tenant_id):
            if plan.day < today:
                await repository.forget_request(tenant_id, plan.id)
            else:
                work.append(_Work(plan.date_key, plan.day, plan.name, plan.owner_products))
        if not asked_only:
            made = {(p.date_key, p.day) for p in await repository.plans(tenant_id, since=today)}
            due = kept_occurrences(
                await repository.rows(tenant_id),
                country,
                start=today + timedelta(days=1),
                end=today + timedelta(days=PLAN_DAYS_BEFORE + 1),
            )
            work += [
                _Work(o.date_key, o.day, o.name)
                for o in due
                if o.day is not None and (o.date_key, o.day) not in made
            ]
        work = work[:MAX_PLANS_PER_RUN]
        if not work:
            return result
        tenant = await TenantRepository(session).get(tenant_id)
        found_catalogue = await catalogue(session, tenant_id)
        known = await facts(session, tenant_id, now=now, titles=found_catalogue.titles)

    shop = (tenant.name if tenant is not None else None) or "the shop"
    for item in work:
        given = _given(item, shop=shop, found=found_catalogue, known=known)
        found = await write_plan(given, llm=llm, prompt=prompt)
        result.calls += found.calls
        if not found.reachable:
            result.stopped = "provider"
            break
        async with db.tenant_session(tenant_id) as session:
            repository = CalendarRepository(session)
            if found.plan is not None:
                await repository.store_plan(
                    tenant_id,
                    date_key=item.date_key,
                    day=item.day,
                    name=item.name,
                    answer=found.plan.stored(),
                    prompt_revision=prompt_revision,
                    at=now,
                )
                result.made += 1
            else:
                await repository.fail_plan(
                    tenant_id,
                    date_key=item.date_key,
                    day=item.day,
                    name=item.name,
                    failure=found.refusals[-1] if found.refusals else "checks",
                    at=now,
                )
                result.failed += 1
            if after_store is not None:
                await after_store(session, tenant_id)
    log.info(
        "grow_plans",
        tenant_id=tenant_id,
        made=result.made,
        failed=result.failed,
        calls=result.calls,
        stopped=result.stopped,
    )
    return result


def _given(item: _Work, *, shop: str, found: Catalogue, known: list[Fact]) -> PlanInput:
    """What the model is given for one date: the owner's products when they chose
    (those still in the catalogue), else the products in stock for it to choose."""
    chosen = [found.every[i] for i in item.chosen or () if i in found.every]
    if chosen:
        return PlanInput(
            shop=shop, name=item.name, day=item.day, products=chosen, facts=known, chosen=True
        )
    return PlanInput(
        shop=shop,
        name=item.name,
        day=item.day,
        products=found.stocked,
        facts=known,
        cut=found.cut,
    )


__all__ = ["MAX_PLANS_PER_RUN", "Catalogue", "PlansResult", "catalogue", "facts", "make_plans"]
