"""a message says which agent wrote it

[ADR-0031] §5. A conversation used to belong to exactly one agent — the shopper
reached ``/v1/care/chat`` or ``/v1/sell/chat`` and never moved — so
``conversations.agent_key`` was the whole truth and a message needed no opinion
of its own.

Dispatch breaks that. A shopper who asks for a jacket and then asks where their
parcel is has changed subject, and the socket now chooses per message, so **one
conversation can hold messages written by different agents**. The merchant reads
that thread the way the shopper experienced it: one conversation, each message
marked with the service that produced it. Two threads would be half a story told
twice, and would hide the handover — which is the part most worth reading while
this is new.

**Nullable, and it stays nullable.** Every message written before today has no
answer to this question, and a backfill would have to invent one from the
conversation's own ``agent_key`` — which is right for every historical row and
would become wrong the moment a conversation spanned two agents, while looking
identical either way. A null here means "written before a message could say",
and that is a true statement rather than a plausible one.

``conversations.agent_key`` is deliberately left alone. It still records the
agent the conversation *started* with, which is what the list view sorts and
filters by; the per-message column is what the transcript renders.

Revision ID: 3f8a6c04d1b7
Revises: 149d17e9028b
Created: 2026-09-01 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8a6c04d1b7"
down_revision: str | None = "149d17e9028b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column("agent_key", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_messages", "agent_key")
