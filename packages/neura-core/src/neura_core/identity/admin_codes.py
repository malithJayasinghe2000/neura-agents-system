"""The code from an admin's phone: its key, and the rules for typing it. ADR-0067.

One row per admin in ``admin_codes`` (no ``tenant_id``, like ``platform_admins``):
the key, **encrypted** with the master key and bound to the admin's own user id
(``neura_core.crypto``, as a shop's credentials are), whether setup was finished,
the last step that matched (so a code works once), and the wrong-code count.

* **Setup** makes a key the first time it is asked for, and gives the same one
  until a first correct code finishes it (G116); after that :func:`start_setup`
  refuses, so the key is never shown again.
* **5 wrong codes in a row stop the admin for 15 minutes**, and while stopped even
  the right code is refused. A correct code clears the count.
* :func:`reset` deletes the row: the admin sets up a new phone (R55).

The code itself is never stored or logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Table, Text, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.crypto import decrypt, encrypt
from neura_core.db import metadata
from neura_core.identity.totp import matching_step, new_secret
from neura_core.logging import get_logger

log = get_logger(__name__)

ADMIN_CODES = "admin_codes"
MAX_WRONG = 5
STOPPED_FOR = timedelta(minutes=15)

admin_codes = Table(
    ADMIN_CODES,
    metadata,
    Column("user_id", String(64), primary_key=True),
    #: The key, encrypted; bound to ``user_id``, so a row copied to another admin
    #: will not decrypt.
    Column("secret", Text, nullable=False),
    Column("confirmed_at", DateTime(timezone=True), nullable=True),
    Column("last_step", BigInteger, nullable=True),
    Column("wrong", Integer, nullable=False, server_default="0"),
    Column("stopped_until", DateTime(timezone=True), nullable=True),
)


class CodeResult(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    #: 5 wrong codes: nothing is checked until ``stopped_until``.
    STOPPED = "stopped"
    #: No key yet (or setup was already finished, for :func:`confirm_setup`).
    NOT_READY = "not_ready"


class SetupFinishedError(Exception):
    """Setup is done; the key is never shown again."""


@dataclass(frozen=True, slots=True)
class _Row:
    secret: str
    confirmed: bool
    last_step: int | None
    wrong: int
    stopped_until: datetime | None


def _aad(user_id: str) -> bytes:
    return f"admin-code:{user_id}".encode()


async def _row(session: AsyncSession, user_id: str, kek: str) -> _Row | None:
    found = (
        await session.execute(select(admin_codes).where(admin_codes.c.user_id == user_id))
    ).first()
    if found is None:
        return None
    return _Row(
        secret=decrypt(found.secret, kek, aad=_aad(user_id)),
        confirmed=found.confirmed_at is not None,
        last_step=found.last_step,
        wrong=found.wrong,
        stopped_until=found.stopped_until,
    )


async def has_code(session: AsyncSession, user_id: str) -> bool:
    """Whether this admin has finished setting up their phone."""
    confirmed = await session.scalar(
        select(admin_codes.c.confirmed_at).where(admin_codes.c.user_id == user_id)
    )
    return confirmed is not None


async def start_setup(session: AsyncSession, user_id: str, *, kek: str) -> str:
    """The key to set up, made the first time this admin asks. Raises
    :class:`SetupFinishedError` once setup is done.

    **Until setup is finished, every request gets the same key** (G116): the
    setup page asks when it opens, a page can open twice at once, and two new
    keys would show one and store the other. So the first key written wins
    (``ON CONFLICT DO NOTHING``) and every request reads that one back.
    """
    if await has_code(session, user_id):
        raise SetupFinishedError(user_id)
    await session.execute(
        pg_insert(admin_codes)
        .values(user_id=user_id, secret=encrypt(new_secret(), kek, aad=_aad(user_id)), wrong=0)
        .on_conflict_do_nothing(index_elements=[admin_codes.c.user_id])
    )
    row = await _row(session, user_id, kek)
    if row is None or row.confirmed:
        raise SetupFinishedError(user_id)
    return row.secret


async def confirm_setup(
    session: AsyncSession, user_id: str, code: str, *, kek: str, now: datetime | None = None
) -> CodeResult:
    """The first code, which finishes setup."""
    row = await _row(session, user_id, kek)
    if row is None or row.confirmed:
        return CodeResult.NOT_READY
    return await _check(session, user_id, row, code, now=now or datetime.now(UTC), finish=True)


async def check_code(
    session: AsyncSession, user_id: str, code: str, *, kek: str, now: datetime | None = None
) -> CodeResult:
    """A code typed at sign-in."""
    row = await _row(session, user_id, kek)
    if row is None or not row.confirmed:
        return CodeResult.NOT_READY
    return await _check(session, user_id, row, code, now=now or datetime.now(UTC), finish=False)


async def _check(
    session: AsyncSession, user_id: str, row: _Row, code: str, *, now: datetime, finish: bool
) -> CodeResult:
    if row.stopped_until is not None and row.stopped_until > now:
        log.info("admin_code_stopped", user_id=user_id)
        return CodeResult.STOPPED
    step = matching_step(row.secret, code, now=now, last_step=row.last_step)
    where = admin_codes.c.user_id == user_id
    if step is None:
        wrong = row.wrong + 1
        stopped = wrong >= MAX_WRONG
        await session.execute(
            admin_codes.update()
            .where(where)
            .values(
                wrong=0 if stopped else wrong,
                stopped_until=now + STOPPED_FOR if stopped else None,
            )
        )
        log.info("admin_code_wrong", user_id=user_id, stopped=stopped)
        return CodeResult.STOPPED if stopped else CodeResult.WRONG
    values: dict[str, Any] = {"last_step": step, "wrong": 0, "stopped_until": None}
    if finish:
        values["confirmed_at"] = now
    await session.execute(admin_codes.update().where(where).values(**values))
    log.info("admin_code_ok", user_id=user_id, setup=finish)
    return CodeResult.OK


async def reset(session: AsyncSession, user_id: str) -> bool:
    """Clear this admin's code: they set up a new phone (R55). False if none."""
    result = await session.execute(delete(admin_codes).where(admin_codes.c.user_id == user_id))
    return bool(getattr(result, "rowcount", 0))


__all__ = [
    "ADMIN_CODES",
    "MAX_WRONG",
    "STOPPED_FOR",
    "CodeResult",
    "SetupFinishedError",
    "admin_codes",
    "check_code",
    "confirm_setup",
    "has_code",
    "reset",
    "start_setup",
]
