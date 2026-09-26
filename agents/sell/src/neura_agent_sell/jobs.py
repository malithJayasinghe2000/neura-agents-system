"""SELL's background work: computing one product's pairing.

[ADR-0045](../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
§2's *"queue a background computation"*, running on
[ADR-0022](../../../../docs/architecture/adr/0022-scheduling-under-rls.md)'s
queue and adding nothing to it — same table, same lease, same dead-lettering,
same worker loop. The only new thing is a handler and the entry point that finds
it.

**This is the only place in SELL that may call a model without a shopper.** It
exists so that no shopper ever waits for one: a cart page that missed the cache
wrote a job row and answered from the word path, and this runs minutes later
against a product nobody is currently looking at.

**Three bounds on what it may spend, because a public endpoint queues it.**
Anyone holding a storefront key can name products this shop has never paired,
and each of those is a model call:

1. **The dedupe key** — one live computation per product, however many cart
   pages missed (``cache.dedupe_key_for``).
2. **The tenant's own daily budget** — read before the call and honoured, so a
   merchant at their hard ceiling stops paying for pairings exactly as they stop
   paying for conversations ([ADR-0015]). This is the bound that matters,
   because it is denominated in the thing being spent.
3. **``MAX_ATTEMPTS`` of two** rather than the queue's five: every retry is
   another model call, and a shopper loses nothing when this dead-letters.

**Every call is metered.** ``MeteredLLM`` wraps the shared client and the spend
is written to the tenant's usage row as ``llm_calls`` with **no turn** — because
it was not one. A background surface that cost money and reported none would be
P5's defect arriving from the other side.
"""

from __future__ import annotations

from typing import Any

from neura_agent_sell.manifest import MANIFEST
from neura_agent_sell.pairing import compute
from neura_agent_sell.pairing.cache import PAIRING_COMPUTE, DatabasePairingCache, source_hash
from neura_agent_sell.prompts import load_prompts, prompt_hashes
from neura_core import ValidationError, get_logger
from neura_core.tenancy import Admission, BudgetLimits, TenantRepository, UsageDelta, UsageMeter

log = get_logger(__name__)

PROMPT_NAME = "pairing"


class PairingProviderError(Exception):
    """The model could not be reached, so nothing was measured and nothing is
    stored. A retry, not a result — see the raise site."""


class PairingComputeHandler:
    """Runs one ``sell.pairing.compute`` job.

    Holds the process-wide store directory and model client, the way
    ``SyncStoreHandler`` holds the first of those and for the same reason: a
    connection pool per job is a connection pool per cart page that missed.
    """

    def __init__(self, stores: Any, llm: Any) -> None:
        self._stores = stores
        self._llm = llm

    async def __call__(self, context: Any) -> str:
        store_id, product_id = _payload(context.job.payload, job_id=context.job.id)

        admission, limits = await _budget(context.db, context.tenant_id)
        if admission is Admission.ESCALATE_ONLY:
            # Completed rather than retried. The merchant is over their ceiling
            # for today; a retry ladder would spend the next attempt on the same
            # refusal, and the next cart page that wants this pairing will queue
            # it again tomorrow for nothing.
            log.warning(
                "pairing_skipped_over_budget",
                tenant_id=context.tenant_id,
                product_id=product_id,
                hard_usd=str(limits.hard),
            )
            return f"skipped {product_id}: tenant is over its daily hard budget"

        connection = await self._stores.connect(context.tenant_id, store_id=store_id)
        metered = _metered(self._llm)

        try:
            anchor = await connection.adapter.get_product(product_id)
            if anchor is None:
                # The page named a product the shop no longer has. Nothing to
                # compute and nothing to store — a row for a product that does
                # not exist is a row nothing will ever read.
                return f"{product_id} is not in this catalogue; nothing computed"

            if not anchor.category_ids:
                # `select.is_complementary` would refuse every candidate, so the
                # model call would be paid for and thrown away. Stored as an
                # empty result with its reason, which is also the answer to a
                # merchant asking why this product never gets suggestions.
                await _write(
                    context,
                    store_id=store_id,
                    product_id=product_id,
                    fingerprint=source_hash(anchor),
                    result=compute.ComputedPairing(product_id=product_id),
                    model="",
                    note="the product has no category, so nothing can be complementary to it",
                )
                return f"{product_id} has no category; stored empty"

            result = await compute.compute(
                anchor,
                adapter=connection.adapter,
                tenant_id=context.tenant_id,
                llm=metered,
                prompt=load_prompts()[PROMPT_NAME],
            )

            if not result.measured:
                # **Raised, so the queue retries and nothing is written.** A
                # provider outage stored as an empty pairing would be permanent:
                # the row would match the live fingerprint for ever and no cart
                # page would ever ask again. One attempt is spent, the backoff
                # runs, and after `MAX_ATTEMPTS` it dead-letters visibly — which
                # costs a shopper nothing, because the word path answered all
                # along.
                raise PairingProviderError(
                    f"the reasoner was unreachable computing {product_id}: {result.provider_error}"
                )

            await _write(
                context,
                store_id=store_id,
                product_id=product_id,
                # **The live text, not the payload's.** A description edited
                # between the queueing and the running of this job would
                # otherwise be stored under the old fingerprint and be treated
                # as valid for text the model never read.
                fingerprint=source_hash(anchor),
                result=result,
                model=_model_name(metered),
                note="" if result.suggested_ids else "no complementary product matched these kinds",
            )
        finally:
            # The adapter holds an HTTP client; one per job and abandoned leaks
            # a connection pool per computation.
            await _close(connection.adapter)
            await _meter(context, metered)

        return (
            f"{product_id}: {len(result.kinds)} kind(s) searched, "
            f"{len(result.suggested_ids)} stored"
        )


async def _budget(db: Any, tenant_id: str) -> tuple[Admission, BudgetLimits]:
    """Where this tenant stands today, before anything is spent.

    Read in its own short transaction, as the turn service reads it — the
    alternative is holding a session open across a model call and a catalogue
    search, which is the connection-starvation shape ``JobContext`` exists to
    prevent.
    """
    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).require(tenant_id)
        spend = await UsageMeter(session).spend_today(tenant_id)

    limits = BudgetLimits.resolve(tenant)
    return limits.admit(spend), limits


async def _write(
    context: Any,
    *,
    store_id: str,
    product_id: str,
    fingerprint: str,
    result: compute.ComputedPairing,
    model: str,
    note: str,
) -> None:
    await DatabasePairingCache(context.db, tenant_id=context.tenant_id, store_id=store_id).put(
        product_id,
        source_hash=fingerprint,
        suggested_ids=result.suggested_ids,
        kinds=result.kinds,
        model=model,
        prompt_hash=prompt_hashes()[PROMPT_NAME],
        note=note,
    )


async def _meter(context: Any, metered: Any) -> None:
    """Charge the tenant for what this job asked of the models.

    ``turns=0`` and ``conversations=0``: nothing here is a turn, and counting
    one would inflate the denominator of every per-turn figure a merchant is
    shown. What is counted is the thing that was actually consumed.
    """
    spend = getattr(metered, "spend", None)
    if spend is None or not spend.calls:
        return

    async with context.db.tenant_session(context.tenant_id) as session:
        await UsageMeter(session).record(
            context.tenant_id,
            MANIFEST.key,
            UsageDelta(
                llm_calls=spend.calls,
                prompt_tokens=spend.prompt_tokens,
                completion_tokens=spend.completion_tokens,
                cost_usd=spend.cost_usd,
            ),
        )


def _payload(payload: dict[str, Any], *, job_id: str) -> tuple[str, str]:
    """Validate what the row says. The column is ``jsonb``, so PostgreSQL cannot.

    Same accepted cost as ``sync.store``'s payload and the same answer: the
    reader validates, and a bad value raises rather than being quietly ignored —
    a job that computed a pairing for the empty string would report success.
    """
    store_id = payload.get("store_id")
    product_id = payload.get("product_id")

    if not isinstance(store_id, str) or not store_id:
        raise ValidationError(
            f"{PAIRING_COMPUTE} payload: store_id must be a non-empty string.",
            details={"job_id": job_id},
        )
    if not isinstance(product_id, str) or not product_id:
        raise ValidationError(
            f"{PAIRING_COMPUTE} payload: product_id must be a non-empty string.",
            details={"job_id": job_id},
        )
    return store_id, product_id


def _metered(llm: Any) -> Any:
    """Wrap the shared client so this job's spend is attributable.

    Imported here rather than at module scope: ``neura_api`` is the deployable
    and this module is imported by ``make eval``'s discovery as well, which has
    no API to import.
    """
    from neura_api.metering import MeteredLLM

    return MeteredLLM(llm)


def _model_name(metered: Any) -> str:
    from neura_llm import ModelRole

    try:
        return str(metered.model_for(ModelRole.REASONER))
    except Exception:
        # A stub client in a test. The row records "we do not know", which is
        # honest; an invented name would be worse than an empty one.
        return ""


async def _close(adapter: object) -> None:
    closer = getattr(adapter, "aclose", None)
    if closer is not None:
        await closer()


def build_handlers(*, stores: Any, llm: Any, **_: Any) -> dict[str, Any]:
    """Every job kind SELL owns, keyed by kind.

    The fifth discovery seam of the same shape as the other four, and the reason
    is theirs unchanged: without it, registering this handler would mean
    ``from neura_agent_sell.jobs import ...`` inside ``neura-api``, and *"one
    codebase, five products"* would stop being structural the moment agent #2
    needed background work.

    ``**_`` so that a deployment supplying more context than this agent uses
    does not break it — the same forgiveness ``build_routes(agent_key)`` shows
    by accepting an argument it barely needs.
    """
    return {PAIRING_COMPUTE: PairingComputeHandler(stores, llm)}


__all__ = ["PROMPT_NAME", "PairingComputeHandler", "PairingProviderError", "build_handlers"]
