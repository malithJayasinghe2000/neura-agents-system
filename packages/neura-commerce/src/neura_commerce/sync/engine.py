"""The sync engine.

Four ways data gets from a merchant's shop into our copy, each covering a
failure of the one before it (docs/architecture/commerce-integration.md §6.2):

* **Backfill** — the full crawl. Resumable, because it is long.
* **Incremental** — "what changed since I last looked". Cheap, and misses
  deletions entirely.
* **Refresh** — one entity, triggered by a webhook. Fast, and silently lossy:
  a dropped webhook leaves no trace anywhere.
* **Reconcile** — compare what we hold against what the shop has, and repair the
  difference. This is the only step that can notice the failures of the other
  three, which is why it exists even though everything above it "works".

**What is synced, and what is not.** Catalogue, categories and policy text are
synced: they change slowly, and semantic search needs them local. Orders and
customers are read live through the adapter instead. An order's status changes
fast, and "your parcel is out for delivery" being an hour stale is a worse
failure than the answer taking 400ms — so the freshest possible read wins
(§6.1).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from neura_commerce.errors import AdapterError, AdapterRateLimitedError
from neura_commerce.identity import EntityKey, EntityType
from neura_commerce.pagination import Cursor, Page, clamp_page_size
from neura_commerce.protocol import CommerceAdapter
from neura_commerce.queries import SyncQuery
from neura_commerce.sync.state import SyncCheckpoint, SyncKey, SyncStateStore
from neura_commerce.sync.store import EntityStore, WriteResult, fingerprint
from neura_commerce.sync.throttle import NoLimit
from neura_core import get_logger
from neura_domain import CanonicalEntity, Capability

log = get_logger(__name__)

#: Entity types kept locally. Orders and customers are deliberately absent —
#: see the module docstring.
SYNCED_TYPES: tuple[EntityType, ...] = (
    EntityType.PRODUCT,
    EntityType.CATEGORY,
    EntityType.POLICY,
)

#: A crawl that never ends is a bug in the shop, not a large catalogue. The cap
#: turns "sync hangs forever" into a reported failure.
MAX_PAGES = 10_000

#: Transient failures worth retrying within a run, before giving up and leaving
#: the checkpoint where it is so the next run resumes.
MAX_ATTEMPTS = 3


class Throttle(Protocol):
    async def acquire(self) -> None: ...

    def pause(self, seconds: float) -> None: ...


@dataclass(slots=True)
class SyncOutcome:
    """What one run did. Reported to the merchant, not only to logs."""

    entity_type: EntityType
    mode: str
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    pages: int = 0
    completed: bool = False
    #: Set when the run stopped early. The checkpoint survives, so the next run
    #: continues rather than restarting.
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return self.created + self.updated

    def absorb(self, result: WriteResult) -> None:
        self.created += result.created
        self.updated += result.updated
        self.unchanged += result.unchanged

    def summary(self) -> str:
        return (
            f"{self.entity_type.value} {self.mode}: "
            f"+{self.created} ~{self.updated} ={self.unchanged} -{self.deleted} "
            f"({self.pages} pages)"
        )


@dataclass(slots=True)
class ReconcileOutcome:
    entity_type: EntityType
    local_count: int = 0
    source_count: int = 0
    repaired: int = 0
    removed: int = 0
    drifted: int = 0
    error: str | None = None

    @property
    def in_sync(self) -> bool:
        return self.error is None and self.repaired == 0 and self.removed == 0


class SyncEngine:
    """Syncs one shop, for one tenant."""

    def __init__(
        self,
        adapter: CommerceAdapter,
        *,
        tenant_id: str,
        entities: EntityStore,
        state: SyncStateStore,
        throttle: Throttle | None = None,
        page_size: int = 100,
    ) -> None:
        self._adapter = adapter
        self._tenant_id = tenant_id
        self._entities = entities
        self._state = state
        self._throttle: Throttle = throttle or NoLimit()
        self._page_size = clamp_page_size(page_size)

    @property
    def platform(self) -> str:
        return self._adapter.platform

    # ── Backfill ─────────────────────────────────────────────────────────────

    async def backfill(self, entity_type: EntityType, *, restart: bool = False) -> SyncOutcome:
        """Crawl everything, resuming from the last checkpoint.

        ``restart=True`` throws the checkpoint away. Needed after a mapping fix,
        when the local copy is known to be wrong rather than merely incomplete.
        """
        outcome = SyncOutcome(entity_type=entity_type, mode="backfill")
        checkpoint = await self._checkpoint(entity_type)

        if restart:
            checkpoint = checkpoint.advanced_to(None)

        if not self._is_readable(entity_type):
            outcome.notes.append(
                f"shop does not declare the capability for {entity_type.value}; nothing synced"
            )
            return outcome

        if not self._supports_pagination(entity_type):
            return await self._sync_unpaginated(entity_type, outcome)

        cursor = checkpoint.cursor
        high_water: datetime | None = None

        for _ in range(MAX_PAGES):
            try:
                page = await self._fetch_page(entity_type, SyncQuery(limit=self._page_size), cursor)
            except AdapterError as exc:
                # The checkpoint is left exactly where it was. That is the whole
                # point of writing it after every page: an interrupted crawl of
                # 40,000 products resumes, it does not start again.
                outcome.error = f"{type(exc).__name__}: {exc}"
                await self._save(checkpoint.advanced_to(cursor))
                return outcome

            result = await self._entities.upsert(page.items)
            outcome.absorb(result)
            outcome.pages += 1
            high_water = _newest(high_water, page.items)

            cursor = page.next_cursor
            checkpoint = checkpoint.advanced_to(cursor)
            await self._save(checkpoint)

            if cursor is None:
                break
        else:
            outcome.error = f"stopped after {MAX_PAGES} pages — the cursor is not terminating"
            return outcome

        await self._save(
            checkpoint.finished(at=_now(), count=outcome.written, high_water=high_water)
        )
        outcome.completed = True
        log.info("sync_backfill_complete", entity_type=entity_type.value, **_counts(outcome))
        return outcome

    # ── Incremental ──────────────────────────────────────────────────────────

    async def incremental(self, entity_type: EntityType) -> SyncOutcome:
        """Fetch what changed since the high-water mark.

        Falls back to a full backfill when the shop cannot filter by timestamp —
        and *says so* in the outcome. Silently syncing nothing would look
        identical to a shop where nothing changed, and the local copy would
        quietly rot.
        """
        outcome = SyncOutcome(entity_type=entity_type, mode="incremental")
        checkpoint = await self._checkpoint(entity_type)

        if Capability.INCREMENTAL_SYNC not in self._capabilities:
            outcome.notes.append("shop does not support updated_since; running a full backfill")
            fallback = await self.backfill(entity_type)
            fallback.notes.extend(outcome.notes)
            fallback.mode = "backfill (no incremental support)"
            return fallback

        if not checkpoint.has_completed_backfill:
            # An incremental pass over a catalogue that was never fully crawled
            # produces a copy with holes in it that no later pass will fill.
            outcome.notes.append("no completed backfill yet; running one first")
            return await self.backfill(entity_type)

        if not self._supports_pagination(entity_type):
            return await self._sync_unpaginated(entity_type, outcome)

        query = SyncQuery(limit=self._page_size, updated_since=checkpoint.updated_through)
        cursor: Cursor | None = None
        high_water: datetime | None = None

        for _ in range(MAX_PAGES):
            try:
                page = await self._fetch_page(entity_type, query, cursor)
            except AdapterError as exc:
                outcome.error = f"{type(exc).__name__}: {exc}"
                return outcome

            result = await self._entities.upsert(page.items)
            outcome.absorb(result)
            outcome.pages += 1
            high_water = _newest(high_water, page.items)

            cursor = page.next_cursor
            if cursor is None:
                break
        else:
            outcome.error = f"stopped after {MAX_PAGES} pages — the cursor is not terminating"
            return outcome

        await self._save(
            checkpoint.finished(at=_now(), count=outcome.written, high_water=high_water)
        )
        outcome.completed = True
        return outcome

    # ── Event-driven ─────────────────────────────────────────────────────────

    async def refresh(self, entity_type: EntityType, external_id: str) -> SyncOutcome:
        """Re-read one entity, because the shop said it changed.

        Idempotent by construction: webhooks are delivered twice, and the second
        delivery must be a no-op rather than a duplicate row.
        """
        outcome = SyncOutcome(entity_type=entity_type, mode="refresh")

        try:
            entity = await self._fetch_one(entity_type, external_id)
        except AdapterError as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            return outcome

        if entity is None:
            # Gone from the shop. A refresh that found nothing is a deletion we
            # would otherwise only discover at the next reconcile.
            removed = await self._entities.delete(self._key(entity_type, external_id))
            outcome.deleted = int(removed)
            outcome.completed = True
            return outcome

        outcome.absorb(await self._entities.upsert([entity]))
        outcome.completed = True
        return outcome

    async def forget(self, entity_type: EntityType, external_id: str) -> SyncOutcome:
        """Handle an explicit deletion event."""
        outcome = SyncOutcome(entity_type=entity_type, mode="delete")
        outcome.deleted = int(await self._entities.delete(self._key(entity_type, external_id)))
        outcome.completed = True
        return outcome

    # ── Reconcile ────────────────────────────────────────────────────────────

    async def reconcile(self, entity_type: EntityType) -> ReconcileOutcome:
        """Compare the local copy against the shop, and repair the difference.

        Event-driven sync drifts silently: a webhook that was never delivered
        leaves nothing behind to notice. Reconciliation is the only mechanism
        that can find that, which is why it runs on a schedule rather than in
        response to anything.

        Three kinds of drift, all repaired here:

        * **Missing** — in the shop, not in our copy. A dropped create.
        * **Stale** — content differs. A dropped update.
        * **Extra** — in our copy, not in the shop. A deletion we never saw. This
          is the one that matters most: the agent recommending a product that no
          longer exists is a visible, embarrassing failure.
        """
        outcome = ReconcileOutcome(entity_type=entity_type)

        if not self._is_readable(entity_type):
            return outcome

        local = await self._entities.fingerprints(self._tenant_id, self.platform, entity_type)
        outcome.local_count = len(local)

        try:
            source = await self._crawl_all(entity_type)
        except AdapterError as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            return outcome

        outcome.source_count = len(source)

        stale: list[CanonicalEntity] = []
        for entity in source:
            if local.get(entity.external_id) != fingerprint(entity):
                stale.append(entity)

        if stale:
            result = await self._entities.upsert(stale)
            outcome.repaired = result.written
            outcome.drifted = len(stale)

        vanished = set(local) - {entity.external_id for entity in source}
        for external_id in vanished:
            if await self._entities.delete(self._key(entity_type, external_id)):
                outcome.removed += 1

        if not outcome.in_sync:
            log.warning(
                "sync_drift_repaired",
                entity_type=entity_type.value,
                repaired=outcome.repaired,
                removed=outcome.removed,
            )

        return outcome

    # ── Whole-shop runs ──────────────────────────────────────────────────────

    async def sync_all(self, *, incremental: bool = True) -> list[SyncOutcome]:
        """Every synced entity type, in order."""
        outcomes = []
        for entity_type in SYNCED_TYPES:
            run = self.incremental if incremental else self.backfill
            outcomes.append(await run(entity_type))
        return outcomes

    async def health(self) -> dict[str, object]:
        """What to show a merchant.

        Sync health is a support question, not an internal metric: "why does the
        agent not know about my new products?" is answered here or by guesswork.
        """
        streams = []
        for entity_type in SYNCED_TYPES:
            checkpoint = await self._checkpoint(entity_type)
            streams.append(
                {
                    "entity_type": entity_type.value,
                    "count": await self._entities.count(
                        self._tenant_id, self.platform, entity_type
                    ),
                    "last_completed": (
                        checkpoint.completed_at.isoformat() if checkpoint.completed_at else None
                    ),
                    "backfill_in_progress": checkpoint.is_backfilling,
                }
            )

        return {"tenant_id": self._tenant_id, "platform": self.platform, "streams": streams}

    # ── Fetching ─────────────────────────────────────────────────────────────

    async def _fetch_page(
        self, entity_type: EntityType, query: SyncQuery, cursor: Cursor | None
    ) -> Page[Any]:
        """One page, throttled, with bounded retries on transient failures."""
        attempt = 0
        while True:
            attempt += 1
            await self._throttle.acquire()
            try:
                if entity_type is EntityType.PRODUCT:
                    return await self._adapter.list_products(query, cursor)
                if entity_type is EntityType.ORDER:
                    return await self._adapter.list_orders(query, cursor)
                raise ValueError(f"{entity_type} is not paginated")
            except AdapterRateLimitedError as exc:
                # The shop asked us to slow down. Honour the number it gave.
                self._throttle.pause(exc.retry_after_s or 5.0)
                if attempt >= MAX_ATTEMPTS:
                    raise
            except AdapterError as exc:
                if not exc.retryable or attempt >= MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(min(2**attempt, 10))

    async def _fetch_one(self, entity_type: EntityType, external_id: str) -> CanonicalEntity | None:
        await self._throttle.acquire()

        if entity_type is EntityType.PRODUCT:
            return await self._adapter.get_product(external_id)
        if entity_type is EntityType.ORDER:
            return await self._adapter.get_order(external_id)
        if entity_type is EntityType.CUSTOMER:
            return await self._adapter.get_customer(external_id)

        # Categories and policies have no single-entity endpoint: they are small
        # collections, so a targeted refresh is a re-read of all of them.
        for entity in await self._fetch_collection(entity_type):
            if entity.external_id == external_id:
                return entity
        return None

    async def _fetch_collection(self, entity_type: EntityType) -> list[CanonicalEntity]:
        await self._throttle.acquire()

        if entity_type is EntityType.CATEGORY:
            return list(await self._adapter.list_categories())
        if entity_type is EntityType.POLICY:
            return list(await self._adapter.get_policies())
        raise ValueError(f"{entity_type} has no collection endpoint")

    async def _crawl_all(self, entity_type: EntityType) -> list[CanonicalEntity]:
        """Everything the shop currently has. Used by reconcile only."""
        if not self._supports_pagination(entity_type):
            return await self._fetch_collection(entity_type)

        found: list[CanonicalEntity] = []
        cursor: Cursor | None = None

        for _ in range(MAX_PAGES):
            page = await self._fetch_page(entity_type, SyncQuery(limit=self._page_size), cursor)
            found.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        return found

    async def _sync_unpaginated(self, entity_type: EntityType, outcome: SyncOutcome) -> SyncOutcome:
        """Categories and policies: one call, no cursor.

        Deletions are handled here rather than left to reconcile, because the
        whole collection is in hand — and a policy page that was taken down must
        stop being quoted immediately, not tomorrow.
        """
        try:
            entities = await self._fetch_collection(entity_type)
        except AdapterError as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            return outcome

        outcome.absorb(await self._entities.upsert(entities))
        outcome.pages = 1

        present = {entity.external_id for entity in entities}
        known = await self._entities.external_ids(self._tenant_id, self.platform, entity_type)
        for external_id in known - present:
            if await self._entities.delete(self._key(entity_type, external_id)):
                outcome.deleted += 1

        checkpoint = await self._checkpoint(entity_type)
        await self._save(
            checkpoint.finished(
                at=_now(), count=outcome.written, high_water=_newest(None, entities)
            )
        )
        outcome.completed = True
        return outcome

    # ── Plumbing ─────────────────────────────────────────────────────────────

    @property
    def _capabilities(self) -> frozenset[Capability]:
        return getattr(self._adapter, "capabilities", frozenset())

    def _is_readable(self, entity_type: EntityType) -> bool:
        required = {
            EntityType.PRODUCT: Capability.PRODUCT_READ,
            EntityType.CATEGORY: Capability.CATEGORY_READ,
            EntityType.POLICY: Capability.POLICY_READ,
            EntityType.ORDER: Capability.ORDER_READ,
            EntityType.CUSTOMER: Capability.CUSTOMER_READ,
        }.get(entity_type)

        return required is None or required in self._capabilities

    @staticmethod
    def _supports_pagination(entity_type: EntityType) -> bool:
        return entity_type in (EntityType.PRODUCT, EntityType.ORDER)

    def _key(self, entity_type: EntityType, external_id: str) -> EntityKey:
        return EntityKey(
            tenant_id=self._tenant_id,
            platform=self.platform,
            entity_type=entity_type,
            external_id=external_id,
        )

    async def _checkpoint(self, entity_type: EntityType) -> SyncCheckpoint:
        key = SyncKey(self._tenant_id, self.platform, entity_type)
        return await self._state.load(key) or SyncCheckpoint(key=key)

    async def _save(self, checkpoint: SyncCheckpoint) -> None:
        await self._state.save(checkpoint)


def _now() -> datetime:
    return datetime.now(UTC)


def _newest(current: datetime | None, entities: list[CanonicalEntity]) -> datetime | None:
    for entity in entities:
        stamp = getattr(entity, "updated_at", None)
        if isinstance(stamp, datetime) and (current is None or stamp > current):
            current = stamp
    return current


def _counts(outcome: SyncOutcome) -> dict[str, int]:
    return {
        "created": outcome.created,
        "updated": outcome.updated,
        "unchanged": outcome.unchanged,
        "pages": outcome.pages,
    }
