"""What the agent *would* have said — the shadow record, and the review queue.

[agent-runtime.md §6](../../../../docs/architecture/agent-runtime.md): *the agent
runs on real traffic, takes no action, and logs what it would have done. Humans
grade it.* This module is the second half of that sentence. The first half —
running the turn — needs no code at all, which is the point: a shadow turn is an
ordinary turn whose reply is withheld, so there is no separate path to keep in
step with the real one.

**Why this is a table and not a flag on the transcript.** A shadow reply was never
said. Putting it in ``conversation_messages`` would make it history, and the next
turn would answer as though the shopper had read it — which is both wrong and
undetectable, because the transcript is exactly what "what happened" is read from
later. The shopper's message *is* written there, because that genuinely was said.

## What is recorded, and why each field is here

Everything a human needs to grade the turn without re-running it, and nothing
that could only be re-derived by guessing:

* ``draft`` — the reply that would have gone out, after ``verify``, before
  rehydration. **Tokenised, like the transcript**: a queue a merchant reads for
  six weeks must not become a store of card numbers (security-model.md §6.2).
* ``state``, ``intent``, ``escalated``, ``grounded``, ``verify_reason`` — the
  facts the graph produced. Open question **E7** asked for exactly this on eval
  failures; a grader needs it for the same reason a developer does.
* ``tools``, ``citations`` — what it looked at. A right answer from the wrong
  lookup is a different grade from a right answer from the right one, and that
  distinction is the whole value of grading (A9 is the same failure class).
* ``cost_usd``, ``latency_ms``, ``llm_calls``, ``tool_calls`` — the scorecard's
  raw material, and the honest answer to "what would this have cost us?".
* ``prompt_revision`` — six weeks later, which prompt wrote this.

## The grade, and the three words it may be

Reviewing is a separate act, by a separate person, at a separate time — so the
verdict is columns on this row rather than a second table, and a row is either
graded or it is not. [agent-runtime.md §6](../../../../docs/architecture/agent-runtime.md)
names the three verdicts and they are taken from it unchanged: **agree ·
disagree · would-have-harmed**.

Three rather than two, and the third is the reason the other two are not enough.
"Disagree" covers a reply that was unhelpful, off-key or simply wrong, and most
disagreements are that. **"Would have harmed" is the one that stops a go-live**:
a wrong order status, an invented refund, a policy stated more generously than
the merchant's own page. Folding it into "disagree" would average the only signal
that matters into the noise of the signal that does not — one harmful turn in
fifty is not "96% agreement", it is a reason not to launch.

## What is deliberately not here

**Sampling.** Every shadowed turn is recorded and none is skipped. Open question
**A4** — how much human review time actually exists — is unanswered, and a
sampling rate chosen before anybody has graded for an hour is a rate invented to
fit an imaginary constraint. The first real hour of grading measures it.

**A deflection rate, a quality score, or any single number.** The scorecard
returns counts beside every rate it reports, because "100% agreement" over two
graded turns and over two hundred look identical otherwise, and this project has
a standing rule against numbers that look like measurements and are not
(CLAUDE.md §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    case,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from neura_core import metadata, new_id
from neura_core.ids import MESSAGE

SHADOW_TURNS = "shadow_turns"


class ShadowVerdict(StrEnum):
    """What a human said about a withheld reply. The three words of §6."""

    AGREE = "agree"
    """It would have sent this. The only verdict that is evidence *for* go-live."""

    DISAGREE = "disagree"
    """Wrong, unhelpful or off-key — but nobody would have been hurt by it."""

    WOULD_HAVE_HARMED = "would_have_harmed"
    """A wrong order status, an invented refund, a policy stated too generously.

    Kept separate from ``DISAGREE`` on purpose. One of these in fifty turns is
    not "96% agreement", it is a reason not to launch, and averaging it into a
    single quality number is how that reason disappears.
    """


#: One shadowed turn. The unit a human grades.
shadow_turns = Table(
    SHADOW_TURNS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("conversation_id", String(64), nullable=False),
    #: The shopper message this answers, in ``conversation_messages``. The
    #: transcript keeps what was said; this keeps what was not.
    Column("message_id", String(64), nullable=False),
    Column("agent_key", String(64), nullable=False),
    #: Which mode withheld it. Only ``shadow`` is written today, and the column
    #: exists so that a row grades the same after `SUGGEST` and `SUPERVISED` are
    #: built — a queue of rows that cannot say why they were withheld is a queue
    #: that has to be re-interpreted later from a deploy date.
    Column("mode", String(16), nullable=False),
    Column("intent", String(64), nullable=True),
    Column("state", String(32), nullable=False),
    #: Tokenised, exactly as the transcript stores the shopper's own words.
    Column("draft", Text, nullable=False),
    Column("escalated", Boolean, nullable=False, server_default="false"),
    Column("grounded", Boolean, nullable=True),
    Column("verify_reason", Text, nullable=False, server_default=""),
    Column("tools", JSONB, nullable=False, server_default="[]"),
    Column("citations", JSONB, nullable=False, server_default="[]"),
    Column("tool_calls", Integer, nullable=False, server_default="0"),
    Column("llm_calls", Integer, nullable=False, server_default="0"),
    Column("cost_usd", Numeric(12, 6), nullable=False, server_default="0"),
    Column("latency_ms", Integer, nullable=False, server_default="0"),
    Column("prompt_revision", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    #: The grade, and null until a human gives one. Nullable is the whole
    #: design: "ungraded" has to be its own value, or an unreviewed turn and a
    #: turn somebody approved become the same row.
    Column("verdict", String(24), nullable=True),
    Column("note", Text, nullable=False, server_default=""),
    #: Who graded it. A free string, because there is no user table yet — and it
    #: is recorded rather than left out, because "who approved this?" is the
    #: first question asked after a bad answer reaches a shopper.
    Column("reviewed_by", String(128), nullable=True),
    Column("reviewed_at", DateTime(timezone=True), nullable=True),
    # The queue is read newest-first for one tenant, which is the only access
    # pattern that exists until the console does.
    Index("ix_shadow_turns_tenant_recent", "tenant_id", "created_at", "id"),
    # And the queue a reviewer actually opens is the *ungraded* one. Partial, so
    # it stays small as graded rows accumulate — the working set is what nobody
    # has looked at yet, however long the tenant has been shadowing.
    Index(
        "ix_shadow_turns_ungraded",
        "tenant_id",
        "created_at",
        postgresql_where=text("verdict IS NULL"),
    ),
)


@dataclass(frozen=True, slots=True)
class ShadowTurn:
    """One withheld reply, as the rest of the system talks about it."""

    tenant_id: str
    conversation_id: str
    message_id: str
    agent_key: str
    mode: str
    state: str
    draft: str
    intent: str | None = None
    escalated: bool = False
    grounded: bool | None = None
    verify_reason: str = ""
    tools: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    llm_calls: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    prompt_revision: str | None = None
    id: str = ""
    created_at: datetime | None = None
    verdict: ShadowVerdict | None = None
    note: str = ""
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @property
    def graded(self) -> bool:
        return self.verdict is not None


@dataclass(frozen=True, slots=True)
class Scorecard:
    """What the shadow queue says so far, with every denominator attached.

    **Counts first, rates second, and never a rate without its count.** "100%
    agreement" over two graded turns and over two hundred read identically, and
    this project's standing rule is that a number which looks like a measurement
    and is not is worse than no number (CLAUDE.md §4). Every rate below is
    ``None`` until something has actually been graded.
    """

    total: int = 0
    graded: int = 0
    agree: int = 0
    disagree: int = 0
    would_have_harmed: int = 0
    escalated: int = 0
    cost_usd: Decimal = Decimal("0")
    #: Summed, not averaged. A mean latency over a handful of turns hides the
    #: tail, and the tail is what a shopper waits behind.
    total_latency_ms: int = 0

    @property
    def ungraded(self) -> int:
        return self.total - self.graded

    @property
    def agreement_rate(self) -> float | None:
        """Agreements over *graded* turns — never over recorded ones.

        Dividing by ``total`` would make a queue nobody has reviewed look like a
        queue that failed review, and would improve on its own every time the
        agent ran. Reviewing is the scarce thing here (open question **A4**), so
        it is the denominator.
        """
        return self.agree / self.graded if self.graded else None

    @property
    def harm_free(self) -> bool | None:
        """Has anything graded been marked as harmful?

        Deliberately a boolean and not a rate. There is no acceptable percentage
        of harmful answers to a shopper about their money, so the go-live
        question is "any?" and not "how many?".
        """
        return None if self.graded == 0 else self.would_have_harmed == 0


class ShadowRepository:
    """The review queue, for one tenant. The session is already tenant-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, turn: ShadowTurn) -> str:
        """Write one shadowed turn. Returns its id.

        Called inside the turn's own transaction, beside the transcript and the
        usage row — so a turn that was withheld from a shopper and lost on the
        way to the queue is not a state this can reach. The alternative, writing
        it afterwards, means the merchant pays for evidence that sometimes is not
        there.
        """
        shadow_id = new_id(MESSAGE)
        await self._session.execute(
            shadow_turns.insert().values(
                tenant_id=turn.tenant_id,
                id=shadow_id,
                conversation_id=turn.conversation_id,
                message_id=turn.message_id,
                agent_key=turn.agent_key,
                mode=turn.mode,
                intent=turn.intent,
                state=turn.state,
                draft=turn.draft,
                escalated=turn.escalated,
                grounded=turn.grounded,
                verify_reason=turn.verify_reason,
                tools=turn.tools,
                citations=turn.citations,
                tool_calls=turn.tool_calls,
                llm_calls=turn.llm_calls,
                cost_usd=turn.cost_usd,
                latency_ms=turn.latency_ms,
                prompt_revision=turn.prompt_revision,
            )
        )
        return shadow_id

    async def pending(
        self,
        tenant_id: str,
        *,
        graded: bool | None = None,
        state: str | None = None,
        verdict: ShadowVerdict | None = None,
        agent_key: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        before: tuple[datetime, str] | None = None,
        limit: int = 50,
    ) -> list[ShadowTurn]:
        """The queue, newest first. ``graded=False`` is the reviewer's working set.

        The other filters narrow a queue a person is working through — by what
        the turn would have done (``state``), by their own verdict, by assistant,
        and by when it was recorded (``since`` inclusive, ``until`` exclusive).
        **None of them samples**: each is chosen by the reader and shown on the
        screen, and every recorded turn is reachable with all of them cleared.
        """
        query = select(shadow_turns).where(
            *_matching(
                tenant_id,
                graded=graded,
                state=state,
                verdict=verdict,
                agent_key=agent_key,
                since=since,
                until=until,
            )
        )

        if before is not None:
            # Keyset pagination on (created_at, id), the same shape the
            # conversation list uses. An OFFSET would re-number the page every
            # time a turn is recorded, which for a queue somebody is working
            # through means skipping rows they have never seen.
            created_at, row_id = before
            query = query.where(
                (shadow_turns.c.created_at < created_at)
                | ((shadow_turns.c.created_at == created_at) & (shadow_turns.c.id < row_id))
            )

        rows = await self._session.execute(
            query.order_by(shadow_turns.c.created_at.desc(), shadow_turns.c.id.desc()).limit(limit)
        )
        return [_from_row(row) for row in rows]

    async def get(self, tenant_id: str, shadow_id: str) -> ShadowTurn | None:
        row = (
            await self._session.execute(
                select(shadow_turns)
                .where(shadow_turns.c.tenant_id == tenant_id)
                .where(shadow_turns.c.id == shadow_id)
            )
        ).first()
        return _from_row(row) if row is not None else None

    async def grade(
        self,
        tenant_id: str,
        shadow_id: str,
        *,
        verdict: ShadowVerdict,
        note: str = "",
        reviewed_by: str = "",
    ) -> bool:
        """Record a human's verdict. Returns whether a row was actually graded.

        **A grade may be changed.** The alternative — first verdict wins — sounds
        safer and is not: a reviewer who mis-clicks would have to be told their
        mistake is permanent, and the pressure that puts on a queue somebody is
        working through quickly is the pressure that produces careless grades.
        ``reviewed_at`` and ``reviewed_by`` always describe the *current*
        verdict; an audit trail of grade changes is a real thing to want and is
        not this, because nothing yet reads one.
        """
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(shadow_turns)
                .where(shadow_turns.c.tenant_id == tenant_id)
                .where(shadow_turns.c.id == shadow_id)
                .values(
                    verdict=verdict.value,
                    note=note,
                    reviewed_by=reviewed_by or None,
                    reviewed_at=datetime.now(UTC),
                )
            ),
        )
        # Zero rows means the id does not exist *for this tenant* — under RLS
        # those are the same thing, and the caller turns both into one 404.
        return bool(result.rowcount)

    async def counts(
        self,
        tenant_id: str,
        *,
        graded: bool | None = None,
        agent_key: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> QueueCounts:
        """How many turns match, split by what they would have done and by verdict.

        The numbers beside a screen's filter buttons. Taken with the same
        filters as :meth:`pending` **except** the two the buttons choose between
        — so each button says how many it would show, given everything else the
        reader has already narrowed by.
        """
        where = _matching(tenant_id, graded=graded, agent_key=agent_key, since=since, until=until)
        by_state = {
            str(row[0]): int(row[1])
            for row in (
                await self._session.execute(
                    select(shadow_turns.c.state, func.count())
                    .where(*where)
                    .group_by(shadow_turns.c.state)
                )
            ).all()
        }
        by_verdict = {
            str(row[0]): int(row[1])
            for row in (
                await self._session.execute(
                    select(shadow_turns.c.verdict, func.count())
                    .where(*where, shadow_turns.c.verdict.is_not(None))
                    .group_by(shadow_turns.c.verdict)
                )
            ).all()
        }
        return QueueCounts(total=sum(by_state.values()), by_state=by_state, by_verdict=by_verdict)

    async def scorecard(self, tenant_id: str, *, agent_key: str | None = None) -> Scorecard:
        """Counts, in one query. Rates are computed on :class:`Scorecard`, with
        their denominators attached."""
        verdict = shadow_turns.c.verdict

        def count_where(value: ShadowVerdict) -> Any:
            return func.count(case((verdict == value.value, 1)))

        query = select(
            func.count(),
            func.count(verdict),
            count_where(ShadowVerdict.AGREE),
            count_where(ShadowVerdict.DISAGREE),
            count_where(ShadowVerdict.WOULD_HAVE_HARMED),
            func.count(case((shadow_turns.c.escalated.is_(True), 1))),
            func.coalesce(func.sum(shadow_turns.c.cost_usd), Decimal("0")),
            func.coalesce(func.sum(shadow_turns.c.latency_ms), 0),
        ).where(shadow_turns.c.tenant_id == tenant_id)

        if agent_key is not None:
            query = query.where(shadow_turns.c.agent_key == agent_key)

        row = (await self._session.execute(query)).one()
        return Scorecard(
            total=int(row[0]),
            graded=int(row[1]),
            agree=int(row[2]),
            disagree=int(row[3]),
            would_have_harmed=int(row[4]),
            escalated=int(row[5]),
            cost_usd=Decimal(str(row[6])),
            total_latency_ms=int(row[7]),
        )


@dataclass(frozen=True, slots=True)
class QueueCounts:
    """Counts of one filtered slice of the queue. Counts only — no rate."""

    total: int = 0
    #: Keyed by the recorded ``state`` (``resolved``, ``escalated``, ...).
    by_state: dict[str, int] = field(default_factory=dict)
    #: Keyed by verdict. A verdict nobody gave is absent, not zero.
    by_verdict: dict[str, int] = field(default_factory=dict)


def _matching(
    tenant_id: str,
    *,
    graded: bool | None = None,
    state: str | None = None,
    verdict: ShadowVerdict | None = None,
    agent_key: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[ColumnElement[bool]]:
    """One definition of the queue's filters, so a page and the counts beside
    it can never disagree about which turns they describe."""
    clauses: list[ColumnElement[bool]] = [shadow_turns.c.tenant_id == tenant_id]
    if graded is True:
        clauses.append(shadow_turns.c.verdict.is_not(None))
    elif graded is False:
        clauses.append(shadow_turns.c.verdict.is_(None))
    if state:
        clauses.append(shadow_turns.c.state == state)
    if verdict is not None:
        clauses.append(shadow_turns.c.verdict == verdict.value)
    if agent_key:
        clauses.append(shadow_turns.c.agent_key == agent_key)
    if since is not None:
        clauses.append(shadow_turns.c.created_at >= since)
    if until is not None:
        clauses.append(shadow_turns.c.created_at < until)
    return clauses


def _from_row(row: Any) -> ShadowTurn:
    return ShadowTurn(
        tenant_id=str(row.tenant_id),
        id=str(row.id),
        conversation_id=str(row.conversation_id),
        message_id=str(row.message_id),
        agent_key=str(row.agent_key),
        mode=str(row.mode),
        intent=row.intent,
        state=str(row.state),
        draft=str(row.draft),
        escalated=bool(row.escalated),
        grounded=row.grounded,
        verify_reason=str(row.verify_reason or ""),
        tools=list(row.tools or []),
        citations=list(row.citations or []),
        tool_calls=int(row.tool_calls),
        llm_calls=int(row.llm_calls),
        cost_usd=Decimal(str(row.cost_usd)),
        latency_ms=int(row.latency_ms),
        prompt_revision=row.prompt_revision,
        created_at=row.created_at,
        verdict=ShadowVerdict(row.verdict) if row.verdict else None,
        note=str(row.note or ""),
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
    )


__all__ = [
    "SHADOW_TURNS",
    "QueueCounts",
    "Scorecard",
    "ShadowRepository",
    "ShadowTurn",
    "ShadowVerdict",
    "shadow_turns",
]
