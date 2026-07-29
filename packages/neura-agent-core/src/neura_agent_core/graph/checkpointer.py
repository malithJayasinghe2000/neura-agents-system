"""Durable conversation state, tenant-scoped.

ADR-0004 chose LangGraph *with a PostgreSQL checkpointer* so a conversation
survives a restart or a deploy mid-turn. This is that checkpointer, written
against our own engine rather than the framework's — see ``schema.py`` for why
(tenancy, and one Postgres driver).

**Every read and write is scoped to a tenant**, and the scoping is not a
parameter callers pass: it comes from the session the checkpointer was
constructed with, which Row-Level Security has already constrained. A
conversation's working state holds customer messages and tool results, so it
belongs under the same isolation as everything else.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_agent_core.graph.schema import agent_checkpoint_writes, agent_checkpoints
from neura_core import get_logger

log = get_logger(__name__)


class PostgresCheckpointer(BaseCheckpointSaver[str]):
    """Checkpoints in the primary database, under Row-Level Security.

    Only the async methods are implemented. The graph runs in an async server
    and a synchronous checkpoint write inside it would block the event loop for
    every tenant — the sync methods raise rather than silently existing.
    """

    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        super().__init__(serde=JsonPlusSerializer())
        self._session = session
        self._tenant_id = tenant_id

    # ── Reading ──────────────────────────────────────────────────────────────

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config.get("configurable", {})
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        query = select(agent_checkpoints).where(
            agent_checkpoints.c.tenant_id == self._tenant_id,
            agent_checkpoints.c.thread_id == thread_id,
            agent_checkpoints.c.checkpoint_ns == namespace,
        )
        if checkpoint_id:
            query = query.where(agent_checkpoints.c.checkpoint_id == checkpoint_id)
        else:
            # No id means "resume from wherever this conversation got to".
            query = query.order_by(agent_checkpoints.c.checkpoint_id.desc())

        row = (await self._session.execute(query.limit(1))).first()
        if row is None:
            return None

        return CheckpointTuple(
            config=_config(thread_id, namespace, row.checkpoint_id),
            checkpoint=self.serde.loads_typed((row.checkpoint_type, row.checkpoint)),
            metadata=cast(CheckpointMetadata, dict(row.checkpoint_metadata or {})),
            parent_config=(
                _config(thread_id, namespace, row.parent_checkpoint_id)
                if row.parent_checkpoint_id
                else None
            ),
            pending_writes=await self._pending_writes(thread_id, namespace, row.checkpoint_id),
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Checkpoint history, newest first — how a past turn is replayed."""
        query = select(agent_checkpoints).where(agent_checkpoints.c.tenant_id == self._tenant_id)

        if config:
            configurable = config.get("configurable", {})
            if thread_id := configurable.get("thread_id"):
                query = query.where(agent_checkpoints.c.thread_id == thread_id)
            if (namespace := configurable.get("checkpoint_ns")) is not None:
                query = query.where(agent_checkpoints.c.checkpoint_ns == namespace)

        if before and (before_id := get_checkpoint_id(before)):
            query = query.where(agent_checkpoints.c.checkpoint_id < before_id)

        query = query.order_by(agent_checkpoints.c.checkpoint_id.desc())
        if limit:
            query = query.limit(limit)

        for row in (await self._session.execute(query)).all():
            yield CheckpointTuple(
                config=_config(row.thread_id, row.checkpoint_ns, row.checkpoint_id),
                checkpoint=self.serde.loads_typed((row.checkpoint_type, row.checkpoint)),
                metadata=cast(CheckpointMetadata, dict(row.checkpoint_metadata or {})),
                parent_config=(
                    _config(row.thread_id, row.checkpoint_ns, row.parent_checkpoint_id)
                    if row.parent_checkpoint_id
                    else None
                ),
            )

    # ── Writing ──────────────────────────────────────────────────────────────

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        configurable = config.get("configurable", {})
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_type, serialised = self.serde.dumps_typed(checkpoint)

        statement = pg_insert(agent_checkpoints).values(
            tenant_id=self._tenant_id,
            thread_id=thread_id,
            checkpoint_ns=namespace,
            checkpoint_id=checkpoint["id"],
            parent_checkpoint_id=configurable.get("checkpoint_id"),
            checkpoint_type=checkpoint_type,
            checkpoint=serialised,
            checkpoint_metadata=_jsonable(metadata),
        )
        # Upsert: a node retried after a transient failure writes the same
        # checkpoint id again, and that must be a no-op rather than a crash.
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "thread_id", "checkpoint_ns", "checkpoint_id"],
                set_={
                    "checkpoint": statement.excluded.checkpoint,
                    "checkpoint_type": statement.excluded.checkpoint_type,
                    "checkpoint_metadata": statement.excluded.checkpoint_metadata,
                },
            )
        )

        return _config(thread_id, namespace, checkpoint["id"])

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Pending writes from a task that has not committed.

        This is what lets a run interrupted *inside* a node resume without
        re-running the work that already succeeded.
        """
        configurable = config.get("configurable", {})
        rows = []

        for index, (channel, value) in enumerate(writes):
            value_type, serialised = self.serde.dumps_typed(value)
            rows.append(
                {
                    "tenant_id": self._tenant_id,
                    "thread_id": configurable["thread_id"],
                    "checkpoint_ns": configurable.get("checkpoint_ns", ""),
                    "checkpoint_id": configurable["checkpoint_id"],
                    "task_id": task_id,
                    "idx": index,
                    "channel": channel,
                    "value_type": value_type,
                    "value": serialised,
                    "task_path": task_path,
                }
            )

        if rows:
            statement = pg_insert(agent_checkpoint_writes).values(rows)
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        "tenant_id",
                        "thread_id",
                        "checkpoint_ns",
                        "checkpoint_id",
                        "task_id",
                        "idx",
                    ],
                    set_={"value": statement.excluded.value},
                )
            )

    async def adelete_thread(self, thread_id: str) -> None:
        """Erase one conversation's state.

        Part of the deletion fan-out: a DSAR that clears the transcript but
        leaves the working state behind has not deleted anything
        (security-model.md §6.2).
        """
        for table in (agent_checkpoint_writes, agent_checkpoints):
            await self._session.execute(
                delete(table).where(
                    table.c.tenant_id == self._tenant_id, table.c.thread_id == thread_id
                )
            )

    # ── Internals ────────────────────────────────────────────────────────────

    async def _pending_writes(
        self, thread_id: str, namespace: str, checkpoint_id: str
    ) -> list[tuple[str, str, Any]]:
        rows = (
            await self._session.execute(
                select(agent_checkpoint_writes)
                .where(
                    agent_checkpoint_writes.c.tenant_id == self._tenant_id,
                    agent_checkpoint_writes.c.thread_id == thread_id,
                    agent_checkpoint_writes.c.checkpoint_ns == namespace,
                    agent_checkpoint_writes.c.checkpoint_id == checkpoint_id,
                )
                .order_by(agent_checkpoint_writes.c.task_id, agent_checkpoint_writes.c.idx)
            )
        ).all()

        return [
            (row.task_id, row.channel, self.serde.loads_typed((row.value_type, row.value)))
            for row in rows
        ]

    # The synchronous half of the interface. Raising beats inheriting a default
    # that would block the event loop for every tenant on this process.
    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        raise NotImplementedError("use aget_tuple — this runtime is async only")

    def put(self, *args: Any, **kwargs: Any) -> RunnableConfig:
        raise NotImplementedError("use aput — this runtime is async only")

    def put_writes(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("use aput_writes — this runtime is async only")


def _config(thread_id: str, namespace: str, checkpoint_id: str) -> RunnableConfig:
    return RunnableConfig(
        configurable={
            "thread_id": thread_id,
            "checkpoint_ns": namespace,
            "checkpoint_id": checkpoint_id,
        }
    )


def _jsonable(metadata: CheckpointMetadata) -> dict[str, Any]:
    """LangGraph's metadata carries values JSONB will not take verbatim."""
    return {
        key: (value if isinstance(value, str | int | float | bool | type(None)) else str(value))
        for key, value in dict(metadata).items()
    }


__all__ = ["PostgresCheckpointer"]
