"""A handed-over shopper waiting for the shop's answer. [ADR-0062].

When an assistant hands a chat over, the shop's team may answer the shopper
later, by email, **from the shop's own email app**: NEURA sends nothing. This
table is what makes *later* possible. One row per chat (a chat asks once), saying
how the shop can reach the shopper:

* ``email``: a shopper who was not signed in typed an address into the chat box
  after the handover. The only shopper data here, and **volunteered** (ADR-0062
  §3, amending ADR-0042 §1): kept for one purpose, that chat's answer, and
  deleted when the team presses *Mark as answered*, or after
  ``RETENTION_HANDOVER_EMAILS_DAYS`` if nobody answers (§4).
* ``customer``: the shopper was signed in, so the shop already holds their email.
  **Nothing of theirs is copied here**; the dashboard reads the address from the
  shop when someone opens the chat (§2, §6). The customer's id is on the
  conversation already (``customer_external_id``, ADR-0057).

**The address never enters the transcript.** The chat box sends it in a request
of its own (``POST /v1/conversations/{id}/email``), never as a chat message, so
it never reaches the guard, the model, a trace or ``conversation_messages``
(§10). That is why it is a table beside the conversation and not a message in it.

**What stays after an answer:** who answered and when, with the email gone. It
names a member of the shop's team, never a shopper, and goes with its
conversation (``ConversationRepository.delete_older_than``).

[ADR-0062]: ../../../../docs/architecture/adr/0062-a-handed-over-shopper-may-leave-an-email-and-the-shop-answers-from-its-own.md
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    String,
    Table,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import metadata

WAITING_ANSWERS = "waiting_answers"

#: The longest address email allows (RFC 5321's path limit, less the brackets).
MAX_EMAIL_CHARS = 254


class WaitingReach(StrEnum):
    """How the shop can reach a waiting shopper."""

    #: An address the shopper typed into the chat box.
    EMAIL = "email"
    #: Signed in to the shop, which holds their email. Nothing copied here.
    CUSTOMER = "customer"


waiting_answers = Table(
    WAITING_ANSWERS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    #: One row per chat: a chat asks once (ADR-0062 §9).
    Column("conversation_id", String(64), primary_key=True),
    Column("reach", String(16), nullable=False),
    #: The typed address. ``NULL`` for a signed-in customer, and once answered.
    Column("email", String(MAX_EMAIL_CHARS), nullable=True),
    #: When the shopper became reachable: the address left, or the handover of a
    #: signed-in customer. What the 30 days are counted from.
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("answered_at", DateTime(timezone=True), nullable=True),
    #: The member of the shop's team who pressed *Mark as answered* (a user id).
    Column("answered_by", String(64), nullable=True),
    CheckConstraint("reach IN ('email', 'customer')", name="reach"),
    # A signed-in customer's address is the shop's, never ours to keep.
    CheckConstraint("reach = 'email' OR email IS NULL", name="customer_has_no_email"),
    # "Who is waiting in this shop", the dashboard's list and count.
    Index("ix_waiting_answers_open", "tenant_id", "answered_at", "created_at"),
)


@dataclass(frozen=True, slots=True)
class WaitingAnswer:
    tenant_id: str
    conversation_id: str
    reach: WaitingReach
    email: str | None
    created_at: datetime
    answered_at: datetime | None = None
    answered_by: str | None = None

    @property
    def waiting(self) -> bool:
        """Still waiting for the shop's answer."""
        return self.answered_at is None


class WaitingAnswerRepository:
    """Every read and write of ``waiting_answers``, under the shop's own RLS."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: str, conversation_id: str) -> WaitingAnswer | None:
        row = (
            await self._session.execute(
                select(waiting_answers).where(
                    waiting_answers.c.tenant_id == tenant_id,
                    waiting_answers.c.conversation_id == conversation_id,
                )
            )
        ).first()
        return _waiting(row) if row is not None else None

    async def for_conversations(
        self, tenant_id: str, conversation_ids: Sequence[str]
    ) -> dict[str, WaitingAnswer]:
        """The rows of these chats, for a list page. Chats with none are absent."""
        if not conversation_ids:
            return {}
        rows = (
            await self._session.execute(
                select(waiting_answers).where(
                    waiting_answers.c.tenant_id == tenant_id,
                    waiting_answers.c.conversation_id.in_(list(conversation_ids)),
                )
            )
        ).all()
        return {row.conversation_id: _waiting(row) for row in rows}

    async def leave_email(self, tenant_id: str, conversation_id: str, email: str) -> bool:
        """Keep the address a handed-over shopper typed. ``False`` when the chat
        already waits (one per chat, and the first address stands)."""
        result = await self._session.execute(
            pg_insert(waiting_answers)
            .values(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                reach=WaitingReach.EMAIL.value,
                email=email,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "conversation_id"])
        )
        return cast("CursorResult[object]", result).rowcount == 1

    async def wait_for_customer(self, tenant_id: str, conversation_id: str) -> None:
        """A signed-in customer was handed over: the chat waits on the shop's own
        record of them. Handed over again after an answer, it waits again."""
        statement = pg_insert(waiting_answers).values(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            reach=WaitingReach.CUSTOMER.value,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "conversation_id"],
                set_={"answered_at": None, "answered_by": None, "created_at": func.now()},
                # Only a customer's row reopens. A typed address that was answered
                # is gone, and a chat asks once.
                where=waiting_answers.c.reach == WaitingReach.CUSTOMER.value,
            )
        )

    async def mark_answered(
        self, tenant_id: str, conversation_id: str, *, answered_by: str
    ) -> bool:
        """*Mark as answered*: the email goes at once (R30). ``False`` when the chat
        was not waiting (never was, or someone marked it first)."""
        result = await self._session.execute(
            update(waiting_answers)
            .where(
                waiting_answers.c.tenant_id == tenant_id,
                waiting_answers.c.conversation_id == conversation_id,
                waiting_answers.c.answered_at.is_(None),
            )
            .values(answered_at=datetime.now(UTC), answered_by=answered_by, email=None)
        )
        return cast("CursorResult[object]", result).rowcount == 1

    async def count_waiting(self, tenant_id: str) -> int:
        """How many shoppers wait for this shop's answer: the menu's count."""
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(waiting_answers)
                .where(
                    waiting_answers.c.tenant_id == tenant_id,
                    waiting_answers.c.answered_at.is_(None),
                )
            )
            or 0
        )

    async def delete_expired(self, tenant_id: str, cutoff: datetime) -> int:
        """Unanswered since before ``cutoff``: the row goes, the email with it, and
        the chat leaves the waiting list (ADR-0062 §4). Answered rows hold no
        address and go with their conversation."""
        result = await self._session.execute(
            delete(waiting_answers).where(
                waiting_answers.c.tenant_id == tenant_id,
                waiting_answers.c.answered_at.is_(None),
                waiting_answers.c.created_at < cutoff,
            )
        )
        return cast("CursorResult[object]", result).rowcount


def _waiting(row: Any) -> WaitingAnswer:
    return WaitingAnswer(
        tenant_id=row.tenant_id,
        conversation_id=row.conversation_id,
        reach=WaitingReach(row.reach),
        email=row.email,
        created_at=row.created_at,
        answered_at=row.answered_at,
        answered_by=row.answered_by,
    )


__all__ = [
    "MAX_EMAIL_CHARS",
    "WAITING_ANSWERS",
    "WaitingAnswer",
    "WaitingAnswerRepository",
    "WaitingReach",
    "waiting_answers",
]
