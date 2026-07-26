#!/usr/bin/env python3
"""Watch the sync engine notice a change you make by hand.

    make sync-watch URL=... TOKEN=...

The difference from ``sync_smoke_test.py``: this one **remembers between runs**.
Run it, edit a product in the shop's admin panel, run it again — the second run
reports exactly what changed and nothing else.

That is the property worth seeing with your own eyes, because it is the one that
decides whether the agent knows about a product a merchant edited five minutes
ago. It cannot be demonstrated inside a single process: a fresh copy has nothing
to compare against, so every product looks new.

The state file here is a **demo aid, not the design**. Real persistence is
PostgreSQL, and it arrives with the database work — the engine talks to
``EntityStore`` and ``SyncStateStore`` and does not care which is behind them,
which is what makes this file possible in forty lines.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from neura_adapters.generic import GenericAdapter
from neura_commerce import EntityType
from neura_commerce.sync import (
    InMemoryEntityStore,
    InMemorySyncStateStore,
    RateLimiter,
    SyncEngine,
)
from neura_commerce.sync.state import SyncCheckpoint, SyncKey
from neura_commerce.sync.store import StoredEntity
from neura_core import configure_logging
from neura_domain import Category, Policy, Product

DEFAULT_STATE = Path(".sync-demo-state.json")

_MODELS: dict[str, Any] = {
    EntityType.PRODUCT.value: Product,
    EntityType.CATEGORY.value: Category,
    EntityType.POLICY.value: Policy,
}


def load(path: Path, entities: InMemoryEntityStore, state: InMemorySyncStateStore) -> bool:
    """Restore the previous run. Returns whether there was one."""
    if not path.exists():
        return False

    saved = json.loads(path.read_text())

    for row in saved["entities"]:
        model = _MODELS[row["entity_type"]]
        entity = model.model_validate(row["entity"])
        entities._rows[tuple(row["key"])] = StoredEntity(
            key=_key(row["key"]),
            neura_id=entity.neura_id,
            fingerprint=row["fingerprint"],
            entity=entity,
        )

    for row in saved["checkpoints"]:
        key = SyncKey(row["tenant_id"], row["platform"], EntityType(row["entity_type"]))
        state._checkpoints[key.as_tuple()] = SyncCheckpoint(
            key=key,
            updated_through=_time(row["updated_through"]),
            completed_at=_time(row["completed_at"]),
            last_run_count=row["last_run_count"],
        )

    return True


def save(path: Path, entities: InMemoryEntityStore, state: InMemorySyncStateStore) -> None:
    rows = entities._rows.values()
    checkpoints = state._checkpoints.values()

    path.write_text(
        json.dumps(
            {
                "entities": [
                    {
                        "key": list(row.key.as_tuple()),
                        "entity_type": row.key.entity_type.value,
                        "fingerprint": row.fingerprint,
                        "entity": row.entity.model_dump(mode="json"),
                    }
                    for row in rows
                ],
                "checkpoints": [
                    {
                        "tenant_id": c.key.tenant_id,
                        "platform": c.key.platform,
                        "entity_type": c.key.entity_type.value,
                        "updated_through": _iso(c.updated_through),
                        "completed_at": _iso(c.completed_at),
                        "last_run_count": c.last_run_count,
                    }
                    for c in checkpoints
                ],
            },
            indent=2,
        )
    )


def _key(parts: list[str]) -> Any:
    from neura_commerce import EntityKey

    return EntityKey(parts[0], parts[1], EntityType(parts[2]), parts[3])


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _time(value: str | None) -> Any:
    from datetime import datetime

    return datetime.fromisoformat(value) if value else None


async def run(url: str, token: str, tenant: str, path: Path) -> int:
    adapter = GenericAdapter(base_url=url, tenant_id=tenant, token=token)
    entities = InMemoryEntityStore()
    state = InMemorySyncStateStore()

    resumed = load(path, entities, state)

    engine = SyncEngine(
        adapter,
        tenant_id=tenant,
        entities=entities,
        state=state,
        throttle=RateLimiter(rate_per_second=10, burst=10),
        page_size=10,
    )

    if not resumed:
        print("\n  First run — building the local copy.\n")
        for outcome in await engine.sync_all(incremental=False):
            print(f"    {outcome.summary()}")

        save(path, entities, state)
        print(
            "\n  Now change something in the shop — edit a product's name or price,"
            "\n  or delete one — then run this again.\n"
        )
        await adapter.aclose()
        return 0

    print("\n  Checking what changed since the last run.\n")

    changed = 0
    for entity_type in (EntityType.PRODUCT, EntityType.CATEGORY, EntityType.POLICY):
        outcome = await engine.incremental(entity_type)
        changed += outcome.created + outcome.updated + outcome.deleted
        print(f"    {outcome.summary()}")

    print("\n  Reconciling — catches deletions and anything the timestamps missed.\n")
    for entity_type in (EntityType.PRODUCT, EntityType.CATEGORY, EntityType.POLICY):
        reconcile = await engine.reconcile(entity_type)
        changed += reconcile.repaired + reconcile.removed
        print(
            f"    {entity_type.value:<9} local={reconcile.local_count} "
            f"source={reconcile.source_count} repaired={reconcile.repaired} "
            f"removed={reconcile.removed}"
        )

    save(path, entities, state)

    print()
    if changed:
        print(f"  \033[32mPicked up {changed} change(s).\033[0m\n")
    else:
        print(
            "  Nothing changed in the shop since the last run.\n"
            "  Edit a product in the admin panel and run this again.\n"
        )

    await adapter.aclose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch sync notice a real edit.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--tenant-id", default="tn_watch")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--reset", action="store_true", help="Forget the local copy and start over."
    )
    args = parser.parse_args()

    if args.reset and args.state.exists():
        args.state.unlink()
        print(f"  removed {args.state}")

    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(args.url, args.token, args.tenant_id, args.state)))


if __name__ == "__main__":
    main()
