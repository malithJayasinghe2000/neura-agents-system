"""Tables for conversation state and the audit log.

**Why these are ours rather than LangGraph's.** LangGraph ships a PostgreSQL
checkpointer, and not using it was a deliberate choice with two reasons:

1. **Tenancy.** Its tables are keyed by ``thread_id`` and have no ``tenant_id``,
   so they would be the only business tables in the system outside Row-Level
   Security — a hole in ADR-0008 that the "every tenant table has a policy" test
   could not even see, because the column it looks for would not exist. A
   conversation's working state contains customer messages and tool results;
   that is exactly the data isolation is for.
2. **One driver.** It requires ``psycopg`` and a ``libpq`` binary, while
   everything else here speaks ``asyncpg``. Two Postgres drivers in one process
   is weight a sovereign deployment carries for no benefit (ADR-0005's
   reasoning about extra moving parts applies to dependencies too).

The cost is implementing five async methods against a documented interface. That
is a bounded, one-time cost, and the interface is stable.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from neura_core import metadata

CHECKPOINTS = "agent_checkpoints"
CHECKPOINT_WRITES = "agent_checkpoint_writes"
AUDIT_LOG = "audit_log"


#: One snapshot of a conversation's working state, written after every node.
#: This is what makes a worker restart resume a turn instead of losing it.
agent_checkpoints = Table(
    CHECKPOINTS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    # LangGraph's own vocabulary. Kept verbatim rather than renamed: a reader
    # comparing this against the framework's docs should not have to translate.
    Column("thread_id", String(128), primary_key=True),
    Column("checkpoint_ns", String(255), primary_key=True, server_default=""),
    Column("checkpoint_id", String(64), primary_key=True),
    Column("parent_checkpoint_id", String(64), nullable=True),
    Column("checkpoint_type", String(64), nullable=False),
    Column("checkpoint", LargeBinary, nullable=False),
    Column("checkpoint_metadata", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Resuming reads the newest checkpoint for a thread, so that is the index.
    Index(
        "ix_agent_checkpoints_thread_recent",
        "tenant_id",
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
    ),
)


#: Pending writes from a task that has not committed yet — how LangGraph
#: recovers a run interrupted mid-node rather than mid-graph.
agent_checkpoint_writes = Table(
    CHECKPOINT_WRITES,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("thread_id", String(128), primary_key=True),
    Column("checkpoint_ns", String(255), primary_key=True, server_default=""),
    Column("checkpoint_id", String(64), primary_key=True),
    Column("task_id", String(64), primary_key=True),
    Column("idx", Integer, primary_key=True),
    Column("channel", String(255), nullable=False),
    Column("value_type", String(64), nullable=False),
    Column("value", LargeBinary, nullable=False),
    Column("task_path", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


#: The audit log — append-only, hash-chained (security-model.md §9.1).
#:
#: It serves three purposes at once: incident forensics, EU AI Act traceability,
#: and — most immediately — it is the evidence the injection suite passes, since
#: the eval asserts on the policy engine's *recorded rejections* rather than on
#: whether a reply sounded like a refusal.
audit_log = Table(
    AUDIT_LOG,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("conversation_id", String(64), nullable=True),
    Column("trace_id", String(64), nullable=True),
    Column("sequence", Integer, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("actor", String(128), nullable=False),
    #: Widened from 32 in milestone 1.14, and the reason is worth keeping.
    #: `outcome` was sized for "allow" / "reject" / "escalate". `guard.block`
    #: puts the comma-joined names of every rule that matched here, and two
    #: rules already overflowed 32 characters — which nothing noticed for two
    #: milestones, because until 1.14 every caller passed a `None` audit sink
    #: and the write never happened (open question S5). The first real one
    #: failed on its first attack.
    Column("outcome", String(256), nullable=False),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    # The chain. Each row's hash covers its own content *and* its predecessor's
    # hash, so a deleted or edited row breaks verification of everything after
    # it. An audit log that can be quietly edited is not evidence of anything.
    Column("previous_hash", String(64), nullable=False),
    Column("entry_hash", String(64), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "sequence", name="uq_audit_log_tenant_sequence"),
    Index("ix_audit_log_conversation", "tenant_id", "conversation_id", "sequence"),
)
