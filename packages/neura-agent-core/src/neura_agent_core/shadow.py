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

## What is deliberately not here yet

The **grade**. Reviewing is a separate act by a separate person at a separate
time, and open question **A4** — how much human review capacity actually exists —
is unanswered, so the sampling rate it implies cannot be designed against. The
row is the evidence; the verdict columns arrive with the queue API and the
console that shows them. What exists here is the thing that makes those buildable
at all: rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

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
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import metadata, new_id
from neura_core.ids import MESSAGE

SHADOW_TURNS = "shadow_turns"


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
    # The queue is read newest-first for one tenant, which is the only access
    # pattern that exists until the console does.
    Index("ix_shadow_turns_tenant_recent", "tenant_id", "created_at", "id"),
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

    async def pending(self, tenant_id: str, *, limit: int = 50) -> list[ShadowTurn]:
        """The queue, newest first.

        Deliberately unfiltered by a grade, because there is no grade column yet
        — see the module docstring. When there is, this is where "ungraded" goes,
        and a caller written against this signature keeps working.
        """
        rows = await self._session.execute(
            select(shadow_turns)
            .where(shadow_turns.c.tenant_id == tenant_id)
            .order_by(shadow_turns.c.created_at.desc(), shadow_turns.c.id.desc())
            .limit(limit)
        )
        return [_from_row(row) for row in rows]


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
    )


__all__ = ["SHADOW_TURNS", "ShadowRepository", "ShadowTurn", "shadow_turns"]
