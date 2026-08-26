"""The review queue, assembled with the evidence the draft was checked against.

`shadow.py` records what the agent *would* have said. This module is what a
human reads in order to grade it, and the difference between the two is one
sentence from [console.md §3.2](../../../../docs/console.md):

> **Show the evidence, not just the reply.** A grader who cannot see what the
> agent was working from is grading fluency.

That is open question **E7** restated as a screen. A failed eval case was
undiagnosable because the harness recorded ``composed chars=51`` and threw the
text away; a review queue that shows a fluent paragraph and nothing else asks a
merchant to make the same judgement with less. So a :class:`ReviewItem` carries
three things a ``shadow_turns`` row does not:

* **the shopper's question**, which lives in ``conversation_messages`` because it
  genuinely was said and belongs in the transcript (shadow.py). A reply without
  its question is not gradeable at all, and this is the piece most easily
  forgotten — the row *looks* complete without it.
* **the sources it cited**, resolved to the merchant's own text out of
  ``document_chunks``. "Cited policy:returns" is a reference; the returns policy
  is evidence.
* **an explicit statement of what is not recorded.** A tool citation names the
  lookup and not the record it returned, deliberately — the record is customer
  data and lives under the audit log's retention policy (`serving.Citation`).
  The queue says so rather than showing an empty panel, for the same reason
  [ADR-0020](../../../../docs/architecture/adr/0020-a-withheld-turn-says-so.md)
  gave a withheld reply words: silence is the one outcome indistinguishable
  from a bug.

## What is deliberately approximate, and says so

A citation is ``type:id`` with the chunk index stripped, so the *source* is
recoverable and **the exact chunk the retriever returned is not**. The queue
therefore shows the source document and marks it as the document rather than the
passage. Widening a citation back to chunk precision changes what every
integrator is promised (api-design.md §7) and is not worth doing silently to
serve one screen; showing a document while implying it was the passage would be
the invented-evidence version of the same shortcut.

## What is not here

**Sampling.** Every recorded turn is listed. Open question **A4** — how much
human review time exists — is unanswered, and shadow.py already refuses to
invent a rate to fit it. A queue that quietly showed a subset would answer A4
by accident, in the layer least likely to be read.

**A quality score.** :class:`~neura_agent_core.shadow.Scorecard` returns counts
beside every rate, and nothing here computes a second opinion of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from neura_agent_core.conversations import ConversationRepository
from neura_agent_core.rag.schema import document_chunks
from neura_agent_core.shadow import ShadowRepository, ShadowTurn

#: How much of a cited source is shown per turn. A policy page is short; a
#: synced product description occasionally is not, and a queue that renders
#: forty screens of catalogue per row is a queue nobody scrolls to the end of.
#: Truncation is **reported**, never silent — see :attr:`Evidence.truncated`.
EXCERPT_CHARS = 2000

#: Chunks fetched per cited source. A bound rather than a judgement: without one
#: a single mis-indexed source could pull a page of the queue into memory.
MAX_CHUNKS_PER_SOURCE = 12


@dataclass(frozen=True, slots=True)
class Evidence:
    """One thing the draft was checked against, as a grader sees it.

    ``kind`` separates the two cases the codebase has always kept apart rather
    than blurred (`serving.Citation`): a **document** can be shown, and a
    **tool** can only be named.
    """

    kind: str
    """``"document"`` or ``"tool"``."""

    type: str
    """The citation's type — ``policy``, ``faq``, ``product``, or ``tool``."""

    id: str
    """The source id, or the tool's name."""

    excerpt: str = ""
    """The merchant's own text, for a document that is still indexed."""

    truncated: bool = False
    """The source was longer than :data:`EXCERPT_CHARS`. Shown, not hidden."""

    available: bool = False
    """Whether the text above is the evidence itself.

    ``False`` for every tool — by design, not by omission — and for a document
    that has since been deleted or re-indexed under another id. A screen that
    rendered an empty panel in either case would be showing a grader nothing and
    telling them it was everything.
    """

    reason: str = ""
    """Why there is no text, in words a merchant can act on. Empty when there is."""


#: What a tool citation can honestly say. Not a failure — the record it returned
#: is the shopper's own order data, and it is in the audit log under the
#: retention policy that data belongs to, not in a queue read for six weeks.
TOOL_NOT_RECORDED = (
    "This lookup ran. What it returned is customer data and is kept in the "
    "audit log, not in this queue."
)

#: A cited source that is no longer indexed. Re-indexing under a new id and a
#: deletion look identical from here, and saying so is better than picking one.
SOURCE_GONE = (
    "This source is no longer in the search index — it may have been deleted or "
    "re-indexed since this turn ran."
)


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One withheld turn, ready to grade.

    The ``turn`` is unchanged from :class:`~neura_agent_core.shadow.ShadowTurn`;
    everything else on this object was fetched to make it judgeable.
    """

    turn: ShadowTurn

    question: str = ""
    """What the shopper asked, **tokenised** — ``[EMAIL_1]`` rather than an
    address, exactly as the transcript stores it (security-model.md §6.2). The
    screen explains the tokens; it cannot un-tokenise them, because the
    rehydrated text existed only in the reply the shopper saw."""

    question_recorded: bool = True
    """``False`` when the message is no longer in the transcript — a retention
    policy can delete it and leave this graded row behind."""

    asked_at: datetime | None = None

    evidence: list[Evidence] = field(default_factory=list)

    @property
    def has_draft(self) -> bool:
        return bool(self.turn.draft.strip())


class ReviewQueue:
    """The shadow queue plus its evidence, for one tenant.

    The session is already tenant-scoped, so every read below is filtered by RLS
    rather than by a ``WHERE`` this class could forget. ``tenant_id`` is still
    passed explicitly because every repository in this package takes it — a
    query that relies only on the ambient GUC reads as unscoped to whoever
    reviews it next.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._shadow = ShadowRepository(session)
        self._conversations = ConversationRepository(session)

    async def page(
        self,
        tenant_id: str,
        *,
        graded: bool | None = None,
        before: tuple[datetime, str] | None = None,
        limit: int = 20,
    ) -> list[ReviewItem]:
        """One page of the queue, newest first, each turn with its evidence.

        **No state filter, and that is the decision.** A turn the agent declined
        to answer is in here beside a turn it answered confidently, because those
        are the interesting ones and a queue that hid them would be the
        merchant-facing version of the empty bubble ADR-0020 was written about.
        ``graded`` filters on whether a *human* has looked, which is the only
        axis a reviewer works along.
        """
        turns = await self._shadow.pending(tenant_id, graded=graded, before=before, limit=limit)
        if not turns:
            return []

        questions = await self._conversations.by_ids(tenant_id, [turn.message_id for turn in turns])
        sources = await self._sources(tenant_id, turns)

        items: list[ReviewItem] = []
        for turn in turns:
            message = questions.get(turn.message_id)
            items.append(
                ReviewItem(
                    turn=turn,
                    question=message.content if message else "",
                    question_recorded=message is not None,
                    asked_at=message.created_at if message else None,
                    evidence=_evidence_for(turn, sources),
                )
            )
        return items

    async def one(self, tenant_id: str, shadow_id: str) -> ReviewItem | None:
        turn = await self._shadow.get(tenant_id, shadow_id)
        if turn is None:
            return None

        questions = await self._conversations.by_ids(tenant_id, [turn.message_id])
        message = questions.get(turn.message_id)
        return ReviewItem(
            turn=turn,
            question=message.content if message else "",
            question_recorded=message is not None,
            asked_at=message.created_at if message else None,
            evidence=_evidence_for(turn, await self._sources(tenant_id, [turn])),
        )

    async def _sources(
        self, tenant_id: str, turns: Sequence[ShadowTurn]
    ) -> dict[tuple[str, str], tuple[str, bool]]:
        """Every cited document across a page, in one query.

        Keyed by ``(source_type, source_id)`` and valued by the text and whether
        it was cut short. One statement for the page rather than one per turn:
        a queue that issued a query per citation would be slow in exactly the
        case a merchant has been shadowing long enough for the screen to matter.
        """
        wanted = {
            (str(citation.get("type", "")), str(citation.get("id", "")))
            for turn in turns
            for citation in turn.citations
            if citation.get("type") not in (None, "", "tool") and citation.get("id")
        }
        if not wanted:
            return {}

        rows = (
            await self._session.execute(
                select(
                    document_chunks.c.source_type,
                    document_chunks.c.source_id,
                    document_chunks.c.chunk_index,
                    document_chunks.c.content,
                )
                .where(document_chunks.c.tenant_id == tenant_id)
                # A tuple `IN`, not two independent `IN`s. Two source types can
                # legitimately share an id, and the cross product of the two
                # column lists would show a grader a document the turn never
                # cited while looking exactly like it worked.
                .where(
                    tuple_(document_chunks.c.source_type, document_chunks.c.source_id).in_(
                        sorted(wanted)
                    )
                )
                .order_by(
                    document_chunks.c.source_type,
                    document_chunks.c.source_id,
                    document_chunks.c.chunk_index,
                )
            )
        ).all()

        collected: dict[tuple[str, str], list[str]] = {}
        dropped: set[tuple[str, str]] = set()
        for row in rows:
            key = (str(row.source_type), str(row.source_id))
            chunks = collected.setdefault(key, [])
            if len(chunks) < MAX_CHUNKS_PER_SOURCE:
                chunks.append(str(row.content))
            else:
                dropped.add(key)

        resolved: dict[tuple[str, str], tuple[str, bool]] = {}
        for key, chunks in collected.items():
            joined = "\n\n".join(chunks)
            # Cut by either bound, and the flag says so in both cases. A screen
            # that showed a silently shortened policy would be showing evidence
            # that is not the evidence.
            resolved[key] = (
                joined[:EXCERPT_CHARS],
                key in dropped or len(joined) > EXCERPT_CHARS,
            )
        return resolved


def _evidence_for(
    turn: ShadowTurn, sources: dict[tuple[str, str], tuple[str, bool]]
) -> list[Evidence]:
    """Turn a row's citations into things a person can read.

    Every citation produces an entry, including the ones with nothing behind
    them. Dropping those would leave a grader believing the agent worked from
    less than it did — which is the same error as showing text it never saw,
    pointing the other way.
    """
    evidence: list[Evidence] = []

    for citation in turn.citations:
        kind = str(citation.get("type", ""))
        identifier = str(citation.get("id", ""))
        if not kind or not identifier:
            continue

        if kind == "tool":
            evidence.append(
                Evidence(
                    kind="tool",
                    type=kind,
                    id=identifier,
                    available=False,
                    reason=TOOL_NOT_RECORDED,
                )
            )
            continue

        found = sources.get((kind, identifier))
        if found is None:
            evidence.append(
                Evidence(
                    kind="document",
                    type=kind,
                    id=identifier,
                    available=False,
                    reason=SOURCE_GONE,
                )
            )
            continue

        text, truncated = found
        evidence.append(
            Evidence(
                kind="document",
                type=kind,
                id=identifier,
                excerpt=text,
                truncated=truncated,
                available=True,
            )
        )

    return evidence


def evidence_payload(item: Evidence) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "type": item.type,
        "id": item.id,
        "excerpt": item.excerpt,
        "truncated": item.truncated,
        "available": item.available,
        "reason": item.reason,
    }


__all__ = [
    "EXCERPT_CHARS",
    "MAX_CHUNKS_PER_SOURCE",
    "SOURCE_GONE",
    "TOOL_NOT_RECORDED",
    "Evidence",
    "ReviewItem",
    "ReviewQueue",
    "evidence_payload",
]
