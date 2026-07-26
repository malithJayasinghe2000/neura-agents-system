#!/usr/bin/env python3
"""Run the sync engine against a REAL shop.

    make sync-check URL=http://your-shop/neura/v1 TOKEN=xxx

Unit tests prove the engine handles the failures we imagined. This proves it
handles a real merchant's data, which is a different claim: real catalogues have
products with no description, orders in states nobody planned for, and
timestamps that do not mean quite what the documentation says.

Nothing is written to the shop. Every operation here is a read.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from neura_adapters.generic import GenericAdapter
from neura_commerce import EntityKey, EntityType
from neura_commerce.sync import (
    InMemoryEntityStore,
    InMemorySyncStateStore,
    RateLimiter,
    SyncEngine,
)
from neura_core import configure_logging


def tick(ok: bool) -> str:
    return "\033[32m✔\033[0m" if ok else "\033[31m✘\033[0m"


async def run(url: str, token: str, tenant: str) -> int:
    adapter = GenericAdapter(base_url=url, tenant_id=tenant, token=token)
    entities = InMemoryEntityStore()
    engine = SyncEngine(
        adapter,
        tenant_id=tenant,
        entities=entities,
        state=InMemorySyncStateStore(),
        # A shop we do not know is a shop we assume is small. This is the
        # setting that decides whether a backfill is polite or a denial of
        # service against a merchant's production server.
        throttle=RateLimiter(rate_per_second=10, burst=10),
        page_size=10,
    )

    health = await adapter.health()
    print(f"\n  shop      {health.platform} · spec {health.spec_version}")
    print(f"  declares  {len(health.capabilities)} capabilities\n")
    if not health.usable:
        print("  shop is not usable — nothing to sync\n")
        return 1

    ok = True

    # ── Backfill ─────────────────────────────────────────────────────────────
    print("  BACKFILL")
    for outcome in await engine.sync_all(incremental=False):
        print(f"    {tick(outcome.error is None)} {outcome.summary()}")
        for note in outcome.notes:
            print(f"        note: {note}")
        ok = ok and outcome.error is None

    # ── Idempotency ──────────────────────────────────────────────────────────
    print("\n  BACKFILL AGAIN — must change nothing")
    repeat = await engine.backfill(EntityType.PRODUCT, restart=True)
    idempotent = repeat.created == 0 and repeat.updated == 0
    print(f"    {tick(idempotent)} {repeat.summary()}")
    if not idempotent:
        print("        a second identical crawl wrote rows — the upsert key is wrong")
    ok = ok and idempotent

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
        # Simulate the two failures reconciliation exists for: a create we never
        # heard about, and a stale row from an update we missed.
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

    print()
    if ok:
        print("  \033[32mSync engine works against a real shop.\033[0m\n")
        return 0
    print("  \033[31mSomething failed above.\033[0m\n")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the sync engine against a real shop.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--tenant-id", default="tn_smoke")
    args = parser.parse_args()

    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(args.url, args.token, args.tenant_id)))


if __name__ == "__main__":
    main()
