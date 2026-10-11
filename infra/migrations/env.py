"""Alembic environment.

Two decisions worth knowing before editing this file:

* **The URL comes from settings, never from alembic.ini.** A migration run
  against a different database than the application uses is a bad afternoon,
  and a second copy of the connection string is how that happens.
* **Every table module must be imported below.** Alembic diffs against
  ``neura_core.metadata``; a table whose module was never imported is not in
  that metadata, and autogenerate will cheerfully write a migration that
  *drops* it.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import for side effects: each module registers its tables on `metadata`.
import neura_agent_core.conversations
import neura_agent_core.graph.schema
import neura_agent_core.rag.schema
import neura_agent_core.shadow
import neura_agent_core.shadow_evidence
import neura_agent_core.waiting  # noqa: F401

# The one place an agent's name legitimately appears outside its own package.
# Alembic diffs against `neura_core.metadata`, and a table whose module was never
# imported is absent from it — autogenerate then writes a migration that DROPS
# the table, which is the gotcha AGENTS.md records. An agent that owns a table
# must be imported here; discovery by entry point would be cleverer and would
# fail silently in exactly this way.
import neura_agent_sell.feed.schema
import neura_agent_sell.pairing.schema  # noqa: F401
import neura_commerce.sync.schema  # noqa: F401
import neura_core.idempotency
import neura_core.identity.schema
import neura_core.jobs.schema
import neura_core.observation.schema
import neura_core.tenancy.schema
import neura_core.webhooks.schema  # noqa: F401
from neura_core import get_settings, load_env, metadata

load_env()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The MIGRATION url, not the application one. Migrations create tables and
# policies; the application role deliberately cannot, and running migrations as
# it would fail on the first CREATE.
config.set_main_option("sqlalchemy.url", str(get_settings().database_migration_url))

target_metadata = metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Without this a column changing from VARCHAR(64) to VARCHAR(128)
        # produces an empty migration, and the schema drifts from the models
        # with nothing to show for it.
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout — for review, or for a DBA who applies it by hand."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
