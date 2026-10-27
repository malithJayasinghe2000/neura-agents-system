"""One night's pass over one shop's chats. ADR-0064 §6, grow.md §2.

Reads every assistant reply since the last pass (or the last 30 days the first
time), pairs it with the shopper message it answered, asks the model one
question per reply (:func:`neura_agent_grow.finding.find_gap`), and stores the
checked gaps. **Never while a shopper waits**: this runs on the job queue.

Four things are left out **without a model call**, because none can be a page
gap and each would be paid for: replies to an attack (``blocked``), replies to a
question that is not about the shop (``out_of_scope``), replies with no shopper
message before them, and replies that plainly gave their answer
(:func:`neura_agent_grow.finding.worth_asking`, R47).

**Progress is saved after every reply**, with the gap it found, in one short
transaction. A provider outage stops the pass where it is (the next attempt
starts there), rather than being read as *no gap* and moving on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import aliased

from neura_agent_core.conversations import ConversationState, Role, conversation_messages
from neura_agent_core.gaps import GAP_DAYS, GapKind, PageGap, PageGapRepository, page_gaps
from neura_agent_grow.finding import Exchange, find_gap, worth_asking
from neura_commerce.sync.schema import synced_entities
from neura_core import get_logger

log = get_logger(__name__)

#: The most replies one pass reads. A shop with more is finished the next night.
MAX_REPLIES_PER_PASS = 300

#: Intents that are never a page gap. Strings, not an agent's enum: this is
#: data the turn recorded, and GROW may not import CARE or SELL.
_NEVER_A_GAP = frozenset({"out_of_scope"})


@dataclass(frozen=True, slots=True)
class _Reply:
    message_id: str
    conversation_id: str
    shopper: str
    reply: str
    state: str
    product_ids: tuple[str, ...]
    created_at: datetime
    #: No model is asked: an attack, off-topic, or a plain answer.
    skip: bool = False


@dataclass(slots=True)
class ScanResult:
    read: int = 0
    asked: int = 0
    stored: int = 0
    #: Why the pass stopped early, if it did: ``"provider"`` (unreachable).
    stopped: str = ""

    def summary(self) -> str:
        line = f"{self.read} repl(ies) read · {self.asked} asked · {self.stored} gap(s) stored"
        return line + (f" · stopped: {self.stopped}" if self.stopped else "")


def _product_ids(citations: Any) -> tuple[str, ...]:
    """The products a reply looked at: its ``product:`` citations, in order."""
    found: list[str] = []
    for citation in citations or []:
        if isinstance(citation, dict) and citation.get("type") == "product":
            product_id = str(citation.get("id") or "")
            if product_id and product_id not in found:
                found.append(product_id)
    return tuple(found)


async def _replies(
    session: Any, tenant_id: str, *, since: datetime, until: datetime
) -> list[_Reply]:
    agent = aliased(conversation_messages)
    shopper = aliased(conversation_messages)
    rows = (
        await session.execute(
            select(
                agent.c.id,
                agent.c.conversation_id,
                agent.c.content,
                agent.c.state,
                agent.c.intent,
                agent.c.citations,
                agent.c.created_at,
                shopper.c.content.label("shopper"),
            )
            .select_from(
                agent.join(
                    shopper,
                    and_(
                        shopper.c.tenant_id == agent.c.tenant_id,
                        shopper.c.conversation_id == agent.c.conversation_id,
                        shopper.c.sequence == agent.c.sequence - 1,
                        shopper.c.role == Role.SHOPPER.value,
                    ),
                )
            )
            .where(
                agent.c.tenant_id == tenant_id,
                agent.c.role == Role.AGENT.value,
                agent.c.created_at > since,
                agent.c.created_at <= until,
            )
            .order_by(agent.c.created_at, agent.c.id)
            .limit(MAX_REPLIES_PER_PASS)
        )
    ).all()
    return [
        _Reply(
            message_id=row.id,
            conversation_id=row.conversation_id,
            shopper=row.shopper,
            reply=row.content,
            state=row.state or "",
            product_ids=_product_ids(row.citations),
            created_at=row.created_at,
            skip=row.state == ConversationState.BLOCKED.value
            or (row.intent or "") in _NEVER_A_GAP
            or not worth_asking(
                row.content, handed_over=row.state == ConversationState.ESCALATED.value
            ),
        )
        for row in rows
    ]


async def _titles(session: Any, tenant_id: str, ids: Sequence[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(synced_entities.c.external_id, synced_entities.c.document).where(
                synced_entities.c.tenant_id == tenant_id,
                synced_entities.c.entity_type == "product",
                synced_entities.c.external_id.in_(list(ids)),
            )
        )
    ).all()
    titles = {row.external_id: str((row.document or {}).get("title") or "") for row in rows}
    # A product the catalogue no longer has keeps its id, with no title.
    return {product_id: titles.get(product_id, "") for product_id in ids}


async def _known_facts(
    session: Any, tenant_id: str, ids: Sequence[str], *, since: datetime
) -> dict[str, list[str]]:
    rows = (
        await session.execute(
            select(page_gaps.c.product_id, page_gaps.c.fact)
            .where(page_gaps.c.tenant_id == tenant_id, page_gaps.c.asked_at >= since)
            .where(
                page_gaps.c.product_id.in_(list(ids)) | page_gaps.c.product_id.is_(None)
                if ids
                else page_gaps.c.product_id.is_(None)
            )
            .distinct()
        )
    ).all()
    known: dict[str, list[str]] = {}
    for row in rows:
        known.setdefault(row.product_id or "", []).append(row.fact)
    return {key: sorted(values) for key, values in known.items()}


async def scan_shop(
    db: Any,
    tenant_id: str,
    *,
    llm: object,
    prompt: str,
    prompt_revision: str,
    now: datetime,
    not_before: datetime | None = None,
) -> ScanResult:
    """One pass for one shop. Returns what it did; raises nothing for an outage.

    ``not_before``: when the check was last switched on (ADR-0065). Nothing from
    before it is read, so the chats from while it was off never are (R52).
    """
    result = ScanResult()
    window = now - timedelta(days=GAP_DAYS)
    async with db.tenant_session(tenant_id) as session:
        since = await PageGapRepository(session).scanned_until(tenant_id) or window
        since = max(since, window, not_before or window)
        replies = await _replies(session, tenant_id, since=since, until=now)

    for reply in replies:
        result.read += 1
        if reply.skip:
            async with db.tenant_session(tenant_id) as session:
                await PageGapRepository(session).set_scanned_until(tenant_id, reply.created_at)
            continue
        async with db.tenant_session(tenant_id) as session:
            products = await _titles(session, tenant_id, reply.product_ids)
            known = await _known_facts(session, tenant_id, reply.product_ids, since=window)
        exchange = Exchange(
            shopper=reply.shopper,
            reply=reply.reply,
            handed_over=reply.state == ConversationState.ESCALATED.value,
            products=products,
            known_facts=known,
        )
        found = await find_gap(exchange, llm=llm, prompt=prompt)
        result.asked += 1
        if not found.reachable:
            result.stopped = "provider"
            break
        async with db.tenant_session(tenant_id) as session:
            repository = PageGapRepository(session)
            if found.gap is not None:
                stored = await repository.record(
                    tenant_id,
                    PageGap(
                        conversation_id=reply.conversation_id,
                        message_id=reply.message_id,
                        kind=GapKind.HANDED_OVER if exchange.handed_over else GapKind.HALF_ANSWERED,
                        product_id=found.gap.product_id,
                        fact=found.gap.fact,
                        question=found.gap.question,
                        asked_at=reply.created_at,
                        prompt_revision=prompt_revision,
                    ),
                )
                result.stored += 1 if stored else 0
            await repository.set_scanned_until(tenant_id, reply.created_at)

    if not result.stopped and len(replies) < MAX_REPLIES_PER_PASS:
        # Everything up to now was read: the next pass starts here.
        async with db.tenant_session(tenant_id) as session:
            await PageGapRepository(session).set_scanned_until(tenant_id, now)
    log.info(
        "grow_scan",
        tenant_id=tenant_id,
        read=result.read,
        asked=result.asked,
        stored=result.stored,
        stopped=result.stopped,
    )
    return result


__all__ = ["MAX_REPLIES_PER_PASS", "ScanResult", "scan_shop"]
