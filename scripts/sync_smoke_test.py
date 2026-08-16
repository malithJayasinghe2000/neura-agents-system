#!/usr/bin/env python3
"""Run the sync engine against a REAL shop, into a REAL PostgreSQL.

    make sync-check URL=http://your-shop/neura/v1 TOKEN=xxx

Unit tests prove the engine handles the failures we imagined. This proves it
handles a real merchant's data, which is a different claim: real catalogues have
products with no description, orders in states nobody planned for, and
timestamps that do not mean quite what the documentation says.

**It remembers between runs, and that is the property to watch.** Run it twice.
The first run downloads the catalogue; the second must find everything unchanged
and write nothing. Until 2026-08-16 this script used in-memory stores, so
the second run could only ever repeat the first — which is precisely what a
persistence gap looks like from the outside, and precisely why it survived eight
milestones.

Because the run is now cumulative, the script says which kind of run it was.
A warm run reporting "nothing changed" is the pass; a *cold* run reporting the
same thing would mean it synced nothing at all, and printing one as the other is
how a check comes to measure its own fallback.

``--reset`` throws the stored copy away and starts cold again.

Nothing is written to the shop. Every operation against it is a read.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from neura_adapters.generic import GenericAdapter
from neura_commerce import EntityKey, EntityType
from neura_commerce.sync import (
    SYNCED_TYPES,
    DatabaseEntityStore,
    DatabaseSyncStateStore,
    RateLimiter,
    SyncEngine,
)
from neura_core import Database, configure_logging


def tick(ok: bool) -> str:
    return "\033[32m✔\033[0m" if ok else "\033[31m✘\033[0m"


async def forget(db: Database, tenant: str) -> None:
    """Drop this tenant's stored copy. Runs under RLS as the app role."""
    async with db.tenant_session(tenant) as session:
        await session.execute(
            text("DELETE FROM synced_entities WHERE tenant_id = :t"), {"t": tenant}
        )
        await session.execute(
            text("DELETE FROM sync_checkpoints WHERE tenant_id = :t"), {"t": tenant}
        )


async def held(db: Database, tenant: str, platform: str) -> int:
    entities = DatabaseEntityStore(db, tenant)
    return sum([await entities.count(tenant, platform, t) for t in SYNCED_TYPES])


async def run(url: str, token: str, tenant: str, *, reset: bool) -> int:
    db = Database.from_settings()

    # A database connected as a role RLS does not apply to is a refusal, not a
    # warning — see ADR-0008. `ping` is what enforces it.
    if not await db.ping():
        print("\n  \033[31mNo database at DATABASE_URL — run `make up && make migrate`.\033[0m\n")
        return 1

    adapter = GenericAdapter(base_url=url, tenant_id=tenant, token=token)
    entities = DatabaseEntityStore(db, tenant)
    engine = SyncEngine(
        adapter,
        tenant_id=tenant,
        entities=entities,
        state=DatabaseSyncStateStore(db, tenant),
        # A shop we do not know is a shop we assume is small. This is the
        # setting that decides whether a backfill is polite or a denial of
        # service against a merchant's production server.
        throttle=RateLimiter(rate_per_second=10, burst=10),
        page_size=10,
    )

    if reset:
        await forget(db, tenant)
        print("\n  --reset: the stored copy for this tenant was dropped.")

    health = await adapter.health()
    print(f"\n  shop      {health.platform} · spec {health.spec_version}")
    print(f"  declares  {len(health.capabilities)} capabilities")
    if not health.usable:
        print("\n  shop is not usable — nothing to sync\n")
        return 1

    already = await held(db, tenant, adapter.platform)
    cold = already == 0
    print(
        f"  storage   PostgreSQL · tenant {tenant} · "
        + (
            "\033[33mCOLD — nothing held yet\033[0m"
            if cold
            else f"\033[32mWARM — {already} entities already held\033[0m"
        )
        + "\n"
    )

    ok = True

    # ── Sync ─────────────────────────────────────────────────────────────────
    print("  BACKFILL")
    downloaded = 0
    for outcome in await engine.sync_all(incremental=False):
        print(f"    {tick(outcome.error is None)} {outcome.summary()}")
        for note in outcome.notes:
            print(f"        note: {note}")
        ok = ok and outcome.error is None
        downloaded += outcome.written

    # ── Idempotency, within this process ─────────────────────────────────────
    print("\n  BACKFILL AGAIN — must change nothing")
    repeat = await engine.backfill(EntityType.PRODUCT, restart=True)
    idempotent = repeat.created == 0 and repeat.updated == 0
    print(f"    {tick(idempotent)} {repeat.summary()}")
    if not idempotent:
        print("        a second identical crawl wrote rows — the upsert key is wrong")
    ok = ok and idempotent

    # ── Idempotency, across processes ────────────────────────────────────────
    #
    # The one this milestone exists for, and the one the in-memory store could
    # not express: on a warm run the backfill above already found everything.
    print("\n  ACROSS RESTARTS — was anything re-downloaded?")
    if cold:
        print(
            f"    \033[33m—\033[0m first run: {downloaded} entities stored. "
            "Run this again — the second run must write nothing."
        )
    else:
        persisted = downloaded == 0
        print(
            f"    {tick(persisted)} a previous run's copy was found and reused; "
            f"{downloaded} entities re-downloaded"
        )
        if not persisted:
            print("        the stored copy did not survive — this is the 1.8 seam, still open")
        ok = ok and persisted

    # ── Incremental ──────────────────────────────────────────────────────────
    print("\n  INCREMENTAL — only what changed since the backfill")
    incremental = await engine.incremental(EntityType.PRODUCT)
    print(f"    {tick(incremental.error is None)} {incremental.summary()}")
    for note in incremental.notes:
        print(f"        note: {note}")
    ok = ok and incremental.error is None

    # ── Reconciliation ───────────────────────────────────────────────────────
    print("\n  RECONCILE — after deliberately corrupting the local copy")
    ids = sorted(await entities.external_ids(tenant, adapter.platform, EntityType.PRODUCT))
    if ids:
        # Simulate the failure reconciliation exists for: a create we never
        # heard about, because the webhook that announced it was dropped.
        await entities.delete(EntityKey(tenant, adapter.platform, EntityType.PRODUCT, ids[0]))
        print(f"        deleted product {ids[0]} from the local copy")

    reconcile = await engine.reconcile(EntityType.PRODUCT)
    repaired = reconcile.repaired >= 1 and reconcile.error is None
    print(
        f"    {tick(repaired)} local={reconcile.local_count} source={reconcile.source_count} "
        f"repaired={reconcile.repaired} removed={reconcile.removed}"
    )
    ok = ok and repaired

    clean = await engine.reconcile(EntityType.PRODUCT)
    print(f"    {tick(clean.in_sync)} second pass finds nothing left to repair")
    ok = ok and clean.in_sync

    # ── Health ───────────────────────────────────────────────────────────────
    print("\n  SYNC HEALTH (what a merchant would be shown)")
    health_report = await engine.health()
    for stream in health_report["streams"]:  # type: ignore[union-attr,index]
        print(
            f"    {stream['entity_type']:<9} {stream['count']:>4} entities · "
            f"last full sync {stream['last_completed'] or 'never'}"
        )

    await adapter.aclose()
    await db.dispose()

    print()
    if ok:
        print("  \033[32mSync engine works against a real shop, and remembers.\033[0m")
        if cold:
            print("  \033[33mRun it a second time to see the copy survive.\033[0m")
        print()
        return 0
    print("  \033[31mSomething failed above.\033[0m\n")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the sync engine against a real shop.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--tenant-id", default="tn_smoke")
    parser.add_argument(
        "--reset", action="store_true", help="Drop the stored copy and sync from cold."
    )
    args = parser.parse_args()

    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(args.url, args.token, args.tenant_id, reset=args.reset)))


if __name__ == "__main__":
    main()
