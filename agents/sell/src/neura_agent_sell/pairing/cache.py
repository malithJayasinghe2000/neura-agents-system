"""The stored pairing: what it is keyed by, when it stops being valid, and how
a missing one gets computed.

[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
§§2 and 5. Two halves, kept in one file because they are one idea:

* :func:`source_hash` and :class:`PairingCache` — the *rule*, which
  ``orchestrate.py`` depends on and which needs no database to test.
* :class:`DatabasePairingCache` — the rule against PostgreSQL and the job queue.

**Lazy, and the reason is a cost one.** Nothing is precomputed at sync: a
catalogue of 10,000 products where 200 are ever added to a basket costs 200
computations, not 10,000, and the 200 are exactly the products that matter —
popularity is what puts a product in a basket in the first place. The cache
warms itself in the right order with no ranking logic anywhere.

**A missing pairing is never waited for.** :meth:`PairingCache.queue` returns
having written one row; what it queues runs in the worker, minutes later, and
the shopper in front of it gets the word path's answer now. That ordering is
ADR-0045's first non-negotiable and it is the whole reason this is a queue and
not a function call.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select as sql_select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from neura_agent_sell.pairing.schema import sell_pairings
from neura_core import get_logger
from neura_core.db import Database
from neura_core.ids import new_id
from neura_core.jobs import JobQueue
from neura_domain import Product

log = get_logger(__name__)

#: The job kind. One string in one place, because it is written by the request
#: that found a miss and read by the registry that dispatches it.
PAIRING_COMPUTE = "sell.pairing.compute"

#: Row id prefix. Declared here rather than in ``neura_core.ids`` for the reason
#: ``sell_feeds`` mints its own: the constants in core name core's tables, and an
#: agent's table is the agent's. ``new_id`` takes any prefix, so nothing in core
#: has to learn that a pairing exists.
PAIRING_ID_PREFIX = "prg"

#: How many attempts a computation gets before it dead-letters. **Lower than the
#: queue's default of five**, deliberately: every attempt spends a model call,
#: and a product whose text the model cannot make sense of will not start making
#: sense on the fifth try. A dead letter here costs a shopper nothing — the word
#: path answers either way — so failing early is cheap and retrying is not.
MAX_ATTEMPTS = 2

_PAIRINGS = sell_pairings.c


def source_hash(product: Product) -> str:
    """Fingerprint the product text a pairing was computed from.

    **The invalidation, and it is deliberately not a timestamp.** ADR-0045 §5
    discards a pairing when *the product's own text changes*, because that is
    when the reasoning behind it stops applying — a merchant who rewrites a
    walking boot's description as a cycling shoe's has changed what goes with
    it. An age-based rule would answer a different question and would recompute
    every product every N days for nothing.

    Title and description only. Price, stock and category are excluded because a
    pairing does not depend on them — the first two are read live on every
    request anyway, and a category change that mattered would change the text
    with it far more often than not.

    The separator is a NUL so that a title ending where a description begins
    cannot collide with the same words split differently.
    """
    payload = f"{product.title}\x00{product.description or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dedupe_key_for(store_id: str, product_id: str) -> str:
    """One live computation per product, not one per cart page that missed.

    A popular product is added to twenty baskets in a minute, and every one of
    those requests finds the same empty cache. Without this they would queue
    twenty identical model calls; with it they queue one. ADR-0045 §2's *"no
    request triggers more than one computation"* is this line.
    """
    return f"{store_id}:{product_id}"[:128]


@runtime_checkable
class PairingCache(Protocol):
    """What ``orchestrate.py`` needs, and nothing more.

    A Protocol rather than a class so the request path can be tested — and run —
    with no database at all. ``suggest()`` takes ``cache=None`` and behaves
    exactly as it did before ADR-0045, which is what keeps `make pairs-check`'s
    stub mode free and what makes the fallback honest: the word path is not a
    degraded mode here, it is the mode.
    """

    async def get(self, product_id: str, *, source_hash: str) -> list[str] | None:
        """Stored ids for this product, or ``None`` if there is nothing usable.

        ``None`` covers both *never computed* and *computed against text that
        has since changed*, because the caller does the same thing with either:
        answer from the word path now, and queue a computation.
        """
        ...

    async def queue(self, product_id: str, *, source_hash: str) -> None:
        """Ask for this product's pairing to be computed, later, elsewhere."""
        ...


class DatabasePairingCache:
    """:class:`PairingCache` against PostgreSQL and the ADR-0022 job queue.

    Built per request, around the process-wide :class:`Database`. Every
    statement runs inside ``tenant_session``, so Row-Level Security is what
    keeps one merchant's pairings out of another's cart page — not the
    ``WHERE`` clauses, which are here to keep the planner on the index.
    """

    def __init__(self, db: Database, *, tenant_id: str, store_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._store_id = store_id

    async def get(self, product_id: str, *, source_hash: str) -> list[str] | None:
        async with self._db.tenant_session(self._tenant_id) as session:
            row = (
                await session.execute(
                    sql_select(_PAIRINGS.suggested_ids, _PAIRINGS.source_hash)
                    .where(_PAIRINGS.tenant_id == self._tenant_id)
                    .where(_PAIRINGS.store_id == self._store_id)
                    .where(_PAIRINGS.product_id == product_id)
                )
            ).first()

        if row is None:
            return None

        if str(row.source_hash) != source_hash:
            # **Not deleted here**, and that is a decision rather than laziness.
            # This runs on a cart page; a read path that writes takes a lock and
            # spends latency on every visitor who meets a stale row. Refusing to
            # *use* it is the whole of what §5 asks for, and the recomputation
            # this miss queues overwrites it a minute later.
            log.info(
                "pairing_cache_stale",
                tenant_id=self._tenant_id,
                product_id=product_id,
                detail="the product's text changed since this pairing was computed",
            )
            return None

        return [str(value) for value in (row.suggested_ids or [])]

    async def queue(self, product_id: str, *, source_hash: str) -> None:
        """Enqueue one computation, in its own transaction.

        ADR-0022's argument for a durable queue is that the job row commits with
        whatever decided the work was needed. Here the decision is made on a
        read path that has no transaction of its own, so this opens one — the
        exception to that argument rather than a departure from it, and the
        thing being protected is only *"we noticed this was missing"*, which
        costs nothing to notice again.
        """
        async with self._db.tenant_session(self._tenant_id) as session:
            await JobQueue(session).enqueue(
                self._tenant_id,
                PAIRING_COMPUTE,
                payload={
                    "store_id": self._store_id,
                    "product_id": product_id,
                    "source_hash": source_hash,
                },
                dedupe_key=dedupe_key_for(self._store_id, product_id),
                max_attempts=MAX_ATTEMPTS,
            )

    async def put(
        self,
        product_id: str,
        *,
        source_hash: str,
        suggested_ids: list[str],
        kinds: list[str],
        model: str,
        prompt_hash: str,
        note: str = "",
    ) -> None:
        """Write what the worker computed, replacing whatever was there.

        Not on the :class:`PairingCache` Protocol, because the request path must
        not be able to reach it — the only thing that may write a pairing is the
        job that computed one.

        **An empty result is stored, with its reason.** A product whose kinds
        match nothing is a product whose kinds will match nothing tomorrow, and
        a cache that only remembered successes would queue a fresh model call
        from every cart page for ever. ADR-0040 §4 calls empty a result; this is
        what treating it as one costs and buys.
        """
        async with self._db.tenant_session(self._tenant_id) as session:
            values: dict[str, Any] = {
                "id": new_id(PAIRING_ID_PREFIX),
                "tenant_id": self._tenant_id,
                "store_id": self._store_id,
                "product_id": product_id,
                "source_hash": source_hash,
                "suggested_ids": suggested_ids,
                "kinds": kinds,
                "model": model[:128],
                "prompt_hash": prompt_hash,
                "note": note[:500],
            }
            await session.execute(
                pg_insert(sell_pairings)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_sell_pairings_product",
                    set_={
                        name: values[name]
                        for name in (
                            "source_hash",
                            "suggested_ids",
                            "kinds",
                            "model",
                            "prompt_hash",
                            "note",
                        )
                    },
                )
            )


__all__ = [
    "MAX_ATTEMPTS",
    "PAIRING_COMPUTE",
    "PAIRING_ID_PREFIX",
    "DatabasePairingCache",
    "PairingCache",
    "dedupe_key_for",
    "source_hash",
]
