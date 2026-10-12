"""The conversation transcript — the durable record of what was said.

agent-runtime.md §5 specifies three memory tiers. This is the second one:
*Conversation · Postgres · full transcript, resolution, escalation, grades*. The
first (Redis session) and the third (cross-agent shared memory) are still not
built, and are still deliberately not built — the session tier's contents are
recent turns and a redaction map, and 1.12 decided the redaction map must never
outlive the turn.

**This is not the checkpointer, and the difference is worth stating once.**
``graph/checkpointer.py`` stores LangGraph's working state so an interrupted turn
can resume; its rows are an implementation detail of a run, they are opaque
blobs, and they are deleted when a thread is dropped. This stores what a human
would call the conversation: who said what, in order, and how each turn ended.
Two readers need it and neither can use checkpoints:

* **The next turn.** ``AgentState.history`` is declared as a seam and filled by
  whatever starts the turn. Without it "what colours does it come in?" has no
  referent — measured in milestone 1.9, where the pronoun retrieved the Payment
  Policy at 0.502.
* **The merchant.** ``GET /v1/{agent}/conversations`` is a list of conversations
  with a state, and deriving that from pickled checkpoint blobs would make the
  API's contract depend on a framework's serialisation format.

``agent_key`` is data here, never a name this package knows. It arrives from
whichever agent ran, exactly as it does in the usage meter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    delete,
    exists,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from neura_agent_core.graph.schema import agent_checkpoint_writes, agent_checkpoints
from neura_agent_core.waiting import waiting_answers
from neura_core import metadata, new_id
from neura_core.ids import MESSAGE

CONVERSATIONS = "conversations"
CONVERSATION_MESSAGES = "conversation_messages"


class ConversationState(StrEnum):
    """How the most recent turn ended. The ``state`` field of api-design.md §7.

    Deliberately four values and not three: ``blocked`` and ``escalated`` are
    both refusals, and conflating them would hide from a merchant the difference
    between "we recognised an attack and it cost nobody anything" and "a person
    now has to deal with this" — which is most of what ADR-0012 decided.
    """

    RESOLVED = "resolved"
    AWAITING_CUSTOMER = "awaiting_customer"
    ESCALATED = "escalated"
    BLOCKED = "blocked"

    SHADOWED = "shadowed"
    """The agent answered and the shopper was shown nothing (agent-runtime.md §6).

    Added in 1.15, and it is a fifth value for the same reason there were four:
    conflating it with anything else hides something a merchant needs. It is not
    ``resolved`` — nothing was resolved, and a shadow turn counted as a resolution
    would inflate the one number this product will eventually be sold on. It is
    not ``escalated`` either: a shadow turn that escalated did not reach a person,
    because reaching a person is an action and shadow mode takes none.

    **A shadow turn's own outcome is not lost** — whether it would have escalated
    is recorded on the ``shadow_turns`` row, which is where the question "what
    would it have done?" belongs. This state answers the different question the
    transcript is asked: what did the shopper experience?
    """


class Role(StrEnum):
    SHOPPER = "shopper"
    AGENT = "agent"


#: One conversation. The row a merchant lists, filters and opens.
conversations = Table(
    CONVERSATIONS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("agent_key", String(64), nullable=False),
    Column("state", String(32), nullable=False, server_default=ConversationState.RESOLVED.value),
    #: The merchant's own identifier for this conversation, if they gave one.
    #: Conversation ids stay server-issued and unguessable (open question P2);
    #: this is the correlation handle that makes that decision costless to them.
    Column("external_ref", String(128), nullable=True),
    #: What the *store* had already authenticated about the shopper when the
    #: conversation started. Recorded because it is what made an order readable,
    #: and an access decision nobody can reconstruct is an access decision
    #: nobody can review.
    Column("customer_external_id", String(128), nullable=True),
    Column("channel", String(32), nullable=False, server_default="web"),
    Column("locale", String(16), nullable=False, server_default="en"),
    Column("turns", Integer, nullable=False, server_default="0"),
    Column("escalations", Integer, nullable=False, server_default="0"),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Listing is "this tenant's conversations, newest first, optionally by
    # state" — cursor pagination walks it backwards, so that is the index.
    Index("ix_conversations_tenant_recent", "tenant_id", "updated_at", "id"),
)


#: One message. Two rows per answered turn: what the shopper said, what the
#: agent replied.
#:
#: **The shopper's message is stored as the guard left it** — tokenised, so a
#: transcript kept under the merchant's retention policy does not become a
#: long-term store of card numbers and email addresses (security-model.md §6.2).
#: The rehydrated text exists only in the reply the shopper actually saw.
conversation_messages = Table(
    CONVERSATION_MESSAGES,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("conversation_id", String(64), nullable=False),
    #: Ordering within a conversation. A timestamp is not enough: two messages
    #: of one turn are written in the same transaction and can share a clock
    #: reading, and a transcript that renders the reply before the question is
    #: a transcript nobody trusts again.
    Column("sequence", Integer, nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    #: Per-turn outcome, on the agent's message. Everything here is a fact the
    #: graph recorded, not a judgement made later.
    Column("intent", String(64), nullable=True),
    #: Which agent produced this message — [ADR-0031] §5.
    #:
    #: `conversations.agent_key` records the agent a conversation *started*
    #: with, and that used to be the whole truth: a shopper reached one agent's
    #: own route and never moved. A dispatched conversation can change service
    #: mid-thread, so the per-message answer is here and the per-conversation
    #: one stays what the list view sorts by.
    #:
    #: Nullable, and it stays nullable. A message written before dispatch
    #: existed has no answer, and back-filling it from the conversation would
    #: be right for every historical row and wrong the moment one spanned two
    #: agents — while looking identical either way.
    Column("agent_key", String(64), nullable=True),
    Column("state", String(32), nullable=True),
    Column("citations", JSONB, nullable=False, server_default="[]"),
    Column("trace_id", String(64), nullable=True),
    #: Which prompt file produced this answer. CARE stamps it per turn so any
    #: past reply can be traced to the exact prompt revision behind it.
    Column("prompt_revision", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_conversation_messages_thread", "tenant_id", "conversation_id", "sequence"),
)


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    sequence: int
    id: str = ""
    intent: str | None = None
    state: ConversationState | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None
    #: Which agent wrote this message ([ADR-0031] §5). ``None`` on a shopper's
    #: question, and on every message stored before a message could say.
    agent_key: str | None = None


@dataclass(frozen=True, slots=True)
class Conversation:
    tenant_id: str
    id: str
    agent_key: str
    state: ConversationState
    turns: int = 0
    escalations: int = 0
    external_ref: str | None = None
    customer_external_id: str | None = None
    channel: str = "web"
    locale: str = "en"
    started_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationRepository:
    """Transcripts, for one tenant. The session is already tenant-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(
        self,
        tenant_id: str,
        *,
        conversation_id: str,
        agent_key: str,
        external_ref: str | None = None,
        customer_external_id: str | None = None,
        channel: str = "web",
        locale: str = "en",
    ) -> bool:
        """Create the conversation if it does not exist. Returns whether it was new.

        ``ON CONFLICT DO NOTHING`` rather than a read-then-write: two turns of
        the same conversation arriving together must not race into two rows, and
        the answer to "was this the first turn?" decides whether a
        ``conversation.started`` webhook fires.
        """
        result = await self._session.execute(
            pg_insert(conversations)
            .values(
                tenant_id=tenant_id,
                id=conversation_id,
                agent_key=agent_key,
                state=ConversationState.RESOLVED.value,
                external_ref=external_ref,
                customer_external_id=customer_external_id,
                channel=channel,
                locale=locale,
            )
            .on_conflict_do_nothing(index_elements=[conversations.c.tenant_id, conversations.c.id])
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def get(self, tenant_id: str, conversation_id: str) -> Conversation | None:
        row = (
            await self._session.execute(
                select(conversations)
                .where(conversations.c.tenant_id == tenant_id)
                .where(conversations.c.id == conversation_id)
            )
        ).first()
        return None if row is None else _conversation_from_row(row)

    async def list_for(
        self,
        tenant_id: str,
        *,
        state: ConversationState | None = None,
        agent: str | None = None,
        search: str | None = None,
        waiting: bool = False,
        before: tuple[datetime, str] | None = None,
        limit: int = 50,
    ) -> list[Conversation]:
        """Newest first, cursor-paginated on ``(updated_at, id)``.

        Two columns, not one. ``updated_at`` alone is not unique — a busy tenant
        writes several conversations in the same millisecond — and a cursor over
        a non-unique key skips and repeats rows, which is the exact failure
        api-design.md §5 rejects offsets for.

        ``search`` matches what the **shopper** wrote, never the reply: the
        question a merchant remembers is the customer's, and matching the
        assistant's words would find every thread it ever mentioned returns in.

        ``waiting`` keeps the chats whose shopper waits for the shop's answer
        (ADR-0062): an address left, or a signed-in customer, not yet answered.
        """
        query = select(conversations).where(
            *_matching(tenant_id, state=state, agent=agent, search=search, waiting=waiting)
        )
        if before is not None:
            moment, last_id = before
            query = query.where(
                (conversations.c.updated_at < moment)
                | ((conversations.c.updated_at == moment) & (conversations.c.id < last_id))
            )
        rows = (
            await self._session.execute(
                query.order_by(conversations.c.updated_at.desc(), conversations.c.id.desc()).limit(
                    limit
                )
            )
        ).all()
        return [_conversation_from_row(row) for row in rows]

    async def count_for(
        self,
        tenant_id: str,
        *,
        state: ConversationState | None = None,
        agent: str | None = None,
        search: str | None = None,
        waiting: bool = False,
        through: tuple[datetime, str] | None = None,
    ) -> int:
        """How many conversations match — or, with ``through``, how many sort at
        or before that position in :meth:`list_for`'s order.

        The second is what lets a cursor page say *"26-50 of 55"* **without
        becoming an offset**: the position is counted for the label and never
        used to fetch, so a row written meanwhile can shift the words by one but
        can never make a page skip or repeat a row.
        """
        query = (
            select(func.count())
            .select_from(conversations)
            .where(*_matching(tenant_id, state=state, agent=agent, search=search, waiting=waiting))
        )
        if through is not None:
            query = query.where(_at_or_newer(through))
        return int((await self._session.execute(query)).scalar_one())

    async def cursor_for_page_before(
        self,
        tenant_id: str,
        *,
        page_after: tuple[datetime, str],
        size: int,
        state: ConversationState | None = None,
        agent: str | None = None,
        search: str | None = None,
        waiting: bool = False,
    ) -> tuple[datetime, str] | None:
        """The position that fetches the page *before* the one after ``page_after``.

        A keyset cursor only walks forward, and a merchant also wants *Newer*.
        The previous page is the ``size`` rows at or newer than ``page_after``,
        so the cursor that fetches it is the row just newer than all of them.
        ``None`` means there is no such row — the previous page is the first
        page, which is fetched with no cursor at all.
        """
        row = (
            await self._session.execute(
                select(conversations.c.updated_at, conversations.c.id)
                .where(
                    *_matching(tenant_id, state=state, agent=agent, search=search, waiting=waiting)
                )
                .where(_at_or_newer(page_after))
                .order_by(conversations.c.updated_at.asc(), conversations.c.id.asc())
                .offset(size)
                .limit(1)
            )
        ).first()
        return (row[0], str(row[1])) if row is not None else None

    async def first_questions(
        self, tenant_id: str, conversation_ids: Sequence[str]
    ) -> dict[str, str]:
        """The shopper's first message in each conversation, keyed by conversation.

        One line per row of a list — what lets a merchant tell two threads apart
        without opening either. A conversation where the shopper never wrote is
        simply absent from the result, not given an empty string.
        """
        if not conversation_ids:
            return {}
        rows = (
            await self._session.execute(
                select(conversation_messages.c.conversation_id, conversation_messages.c.content)
                .where(
                    conversation_messages.c.tenant_id == tenant_id,
                    conversation_messages.c.conversation_id.in_(list(conversation_ids)),
                    conversation_messages.c.role == Role.SHOPPER.value,
                )
                .order_by(conversation_messages.c.conversation_id, conversation_messages.c.sequence)
                .distinct(conversation_messages.c.conversation_id)
            )
        ).all()
        return {str(row[0]): str(row[1]) for row in rows}

    async def messages(
        self, tenant_id: str, conversation_id: str, *, limit: int = 200
    ) -> list[Message]:
        rows = (
            await self._session.execute(
                select(conversation_messages)
                .where(conversation_messages.c.tenant_id == tenant_id)
                .where(conversation_messages.c.conversation_id == conversation_id)
                .order_by(conversation_messages.c.sequence)
                .limit(limit)
            )
        ).all()
        return [_message_from_row(row) for row in rows]

    async def by_ids(self, tenant_id: str, ids: Sequence[str]) -> dict[str, Message]:
        """Specific messages, by id, keyed by id. Missing ids are simply absent.

        The review queue's reason for existing: a shadowed turn records the
        ``message_id`` of the question it answers and not the question itself,
        because the question genuinely was said and belongs in the transcript
        (shadow.py). Grading needs both, and one query for a page of turns is
        the difference between a screen and a hundred round trips.

        Absent rather than raising, because a message can legitimately be gone —
        a merchant's retention policy deletes transcripts and leaves the graded
        queue behind. The caller renders "no longer in the transcript", which is
        true, instead of failing to render a turn somebody already graded.
        """
        wanted = [i for i in dict.fromkeys(ids) if i]
        if not wanted:
            return {}

        rows = (
            await self._session.execute(
                select(conversation_messages)
                .where(conversation_messages.c.tenant_id == tenant_id)
                .where(conversation_messages.c.id.in_(wanted))
            )
        ).all()
        return {str(row.id): _message_from_row(row) for row in rows}

    async def history(
        self, tenant_id: str, conversation_id: str, *, turns: int = 6
    ) -> list[dict[str, str]]:
        """Recent turns in the shape ``AgentState.history`` expects.

        The **last** ``turns`` messages, returned oldest-first. Bounded because
        the history goes into a prompt: an unbounded transcript is an unbounded
        token bill and, eventually, a context window that silently truncates the
        part that mattered.
        """
        rows = (
            await self._session.execute(
                select(conversation_messages.c.role, conversation_messages.c.content)
                .where(conversation_messages.c.tenant_id == tenant_id)
                .where(conversation_messages.c.conversation_id == conversation_id)
                .order_by(conversation_messages.c.sequence.desc())
                .limit(turns * 2)
            )
        ).all()
        return [{"role": str(row.role), "content": str(row.content)} for row in reversed(rows)]

    async def append_turn(
        self,
        tenant_id: str,
        conversation_id: str,
        *,
        shopper: str,
        reply: str,
        state: ConversationState,
        intent: str | None = None,
        citations: list[dict[str, Any]] | None = None,
        trace_id: str | None = None,
        prompt_revision: str | None = None,
        agent_key: str | None = None,
    ) -> tuple[str, str]:
        """Write both messages of one turn and roll the conversation forward.

        Returns ``(shopper_message_id, agent_message_id)``. The agent's id is
        what api-design.md §7 returns as ``message_id``: it names the reply,
        which is the thing a merchant later disputes.
        """
        next_sequence = await self._next_sequence(tenant_id, conversation_id)
        shopper_id = new_id(MESSAGE)
        agent_id = new_id(MESSAGE)

        # **Both rows carry every key, including the ones only one of them uses.**
        # A multi-row `insert().values([...])` renders its column list from the
        # *first* mapping and silently discards anything that appears only in a
        # later one — no error, no warning, a successful INSERT. Written as two
        # dictionaries with different keys, this dropped `intent`, `state` and
        # `prompt_revision` from every agent message ever stored, while
        # `citations` survived purely because the shopper's row also happened to
        # set it. `prompt_revision` exists so that a reply can be traced back to
        # the prompt that wrote it six weeks later; for as long as this was
        # wrong, it never held anything to trace.
        #
        # So the shopper's row states its `None`s explicitly. They are not
        # padding: they are what makes the column list complete.
        await self._session.execute(
            conversation_messages.insert().values(
                [
                    {
                        "tenant_id": tenant_id,
                        "id": shopper_id,
                        "conversation_id": conversation_id,
                        "sequence": next_sequence,
                        "role": Role.SHOPPER.value,
                        "content": shopper,
                        # A question has no outcome, no intent of its own and no
                        # prompt behind it. The reply is what carries all three.
                        "intent": None,
                        "state": None,
                        "citations": [],
                        "trace_id": trace_id,
                        "prompt_revision": None,
                        # The shopper's question was not written by an agent.
                        # Stated rather than omitted: the column list comes from
                        # this first mapping, so a key missing here is a key
                        # silently dropped from the agent's row too.
                        "agent_key": None,
                    },
                    {
                        "tenant_id": tenant_id,
                        "id": agent_id,
                        "conversation_id": conversation_id,
                        "sequence": next_sequence + 1,
                        "role": Role.AGENT.value,
                        "content": reply,
                        "intent": intent,
                        "state": state.value,
                        "citations": citations or [],
                        "trace_id": trace_id,
                        "prompt_revision": prompt_revision,
                        # Which service answered ([ADR-0031] §5). On the message
                        # rather than only on the conversation, because a
                        # dispatched thread can change agent between turns.
                        "agent_key": agent_key,
                    },
                ]
            )
        )

        await self._session.execute(
            update(conversations)
            .where(conversations.c.tenant_id == tenant_id)
            .where(conversations.c.id == conversation_id)
            .values(
                state=state.value,
                turns=conversations.c.turns + 1,
                escalations=conversations.c.escalations
                + (1 if state is ConversationState.ESCALATED else 0),
                updated_at=datetime.now(UTC),
            )
        )
        return shopper_id, agent_id

    async def append_shopper_message(
        self,
        tenant_id: str,
        conversation_id: str,
        *,
        shopper: str,
        trace_id: str | None = None,
    ) -> str:
        """Write the shopper's message and **no reply**. Returns its id.

        For a shadowed turn (agent-runtime.md §6). The shopper really did say
        this, so it is history; the agent's draft really was not said, so it is
        not. Writing it here anyway — even flagged — would make the next turn
        answer as though the shopper had read it, and that error is invisible
        precisely because the transcript is what "what happened" is later read
        from.

        The conversation still rolls forward. A turn happened, it cost money, and
        a queue of shadowed turns whose conversations look untouched is a queue
        nobody can find their way back from. ``escalations`` deliberately does
        **not** move: a shadow turn that would have escalated reached nobody, and
        counting it would put work in a merchant's escalation figures that no
        colleague ever received.
        """
        sequence = await self._next_sequence(tenant_id, conversation_id)
        message_id = new_id(MESSAGE)

        await self._session.execute(
            conversation_messages.insert().values(
                tenant_id=tenant_id,
                id=message_id,
                conversation_id=conversation_id,
                sequence=sequence,
                role=Role.SHOPPER.value,
                content=shopper,
                trace_id=trace_id,
                citations=[],
            )
        )
        await self._session.execute(
            update(conversations)
            .where(conversations.c.tenant_id == tenant_id)
            .where(conversations.c.id == conversation_id)
            .values(
                state=ConversationState.SHADOWED.value,
                turns=conversations.c.turns + 1,
                updated_at=datetime.now(UTC),
            )
        )
        return message_id

    async def delete_older_than(self, tenant_id: str, cutoff: datetime) -> int:
        """Delete every conversation untouched since ``cutoff``. Returns how many.

        ``RETENTION_CONVERSATIONS_DAYS`` made real (ADR-0042 §3). **Untouched**,
        not *started*: ``updated_at`` moves on every turn, so a conversation a
        shopper came back to last week is not deleted for having begun in June.

        **The fan-out is the point** (security-model.md §6.2). The messages, and
        the agent's checkpointed working state — the same two tables
        ``adelete_thread`` clears, keyed by the conversation id as ``thread_id``
        — go in the same transaction as the row. A sweep that deleted the
        transcript and left the working state would have deleted nothing a
        forensic reader could not reassemble.

        The waiting row a handover left (``waiting_answers``, ADR-0062) goes too.

        **Deliberately left behind:** ``shadow_turns``, the graded review queue
        (``by_ids`` renders a deleted question as *"no longer in the
        transcript"* for exactly this case), and ``audit_log``, which the app
        role cannot delete from at all (ADR-0048 §5).
        """
        expired = (
            select(conversations.c.id)
            .where(conversations.c.tenant_id == tenant_id)
            .where(conversations.c.updated_at < cutoff)
        ).scalar_subquery()

        await self._session.execute(
            delete(conversation_messages)
            .where(conversation_messages.c.tenant_id == tenant_id)
            .where(conversation_messages.c.conversation_id.in_(expired))
        )
        for table in (agent_checkpoint_writes, agent_checkpoints):
            await self._session.execute(
                delete(table)
                .where(table.c.tenant_id == tenant_id)
                .where(table.c.thread_id.in_(expired))
            )
        # A handed-over shopper's row (ADR-0062): an address not yet answered, or
        # who answered. Neither outlives the chat it belongs to.
        await self._session.execute(
            delete(waiting_answers)
            .where(waiting_answers.c.tenant_id == tenant_id)
            .where(waiting_answers.c.conversation_id.in_(expired))
        )
        result = await self._session.execute(
            delete(conversations)
            .where(conversations.c.tenant_id == tenant_id)
            .where(conversations.c.updated_at < cutoff)
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def any_for(self, tenant_id: str) -> bool:
        """Is any conversation left for a future sweep to expire?"""
        return bool(
            await self._session.scalar(
                select(exists().where(conversations.c.tenant_id == tenant_id))
            )
        )

    async def _next_sequence(self, tenant_id: str, conversation_id: str) -> int:
        current = await self._session.scalar(
            select(func.max(conversation_messages.c.sequence))
            .where(conversation_messages.c.tenant_id == tenant_id)
            .where(conversation_messages.c.conversation_id == conversation_id)
        )
        return int(current or 0) + 1


def _matching(
    tenant_id: str,
    *,
    state: ConversationState | None,
    agent: str | None,
    search: str | None,
    waiting: bool = False,
) -> list[ColumnElement[bool]]:
    """The filters a conversation list is narrowed by — one definition, so a
    page, its count and its *Newer* cursor can never disagree about which rows
    they are talking about."""
    clauses: list[ColumnElement[bool]] = [conversations.c.tenant_id == tenant_id]
    if state is not None:
        clauses.append(conversations.c.state == state.value)
    if agent:
        clauses.append(conversations.c.agent_key == agent)
    if search:
        clauses.append(
            exists().where(
                conversation_messages.c.tenant_id == conversations.c.tenant_id,
                conversation_messages.c.conversation_id == conversations.c.id,
                conversation_messages.c.role == Role.SHOPPER.value,
                conversation_messages.c.content.ilike(f"%{_literal(search)}%", escape="\\"),
            )
        )
    if waiting:
        clauses.append(
            exists().where(
                waiting_answers.c.tenant_id == conversations.c.tenant_id,
                waiting_answers.c.conversation_id == conversations.c.id,
                waiting_answers.c.answered_at.is_(None),
            )
        )
    return clauses


def _literal(text: str) -> str:
    """Escape ``LIKE``'s own characters, so a shopper who typed ``50%`` is searched
    for ``50%`` rather than for "50 followed by anything"."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _at_or_newer(position: tuple[datetime, str]) -> ColumnElement[bool]:
    """Rows at ``position`` or ahead of it in newest-first order."""
    moment, row_id = position
    return (conversations.c.updated_at > moment) | (
        (conversations.c.updated_at == moment) & (conversations.c.id >= row_id)
    )


def _conversation_from_row(row: Any) -> Conversation:
    return Conversation(
        tenant_id=str(row.tenant_id),
        id=str(row.id),
        agent_key=str(row.agent_key),
        state=ConversationState(row.state),
        turns=int(row.turns),
        escalations=int(row.escalations),
        external_ref=row.external_ref,
        customer_external_id=row.customer_external_id,
        channel=str(row.channel),
        locale=str(row.locale),
        started_at=row.started_at,
        updated_at=row.updated_at,
    )


def _message_from_row(row: Any) -> Message:
    return Message(
        id=str(row.id),
        role=Role(row.role),
        content=str(row.content),
        sequence=int(row.sequence),
        intent=row.intent,
        state=ConversationState(row.state) if row.state else None,
        citations=list(row.citations or []),
        created_at=row.created_at,
        agent_key=getattr(row, "agent_key", None),
    )


__all__ = [
    "CONVERSATIONS",
    "CONVERSATION_MESSAGES",
    "Conversation",
    "ConversationRepository",
    "ConversationState",
    "Message",
    "Role",
    "conversation_messages",
    "conversations",
]
