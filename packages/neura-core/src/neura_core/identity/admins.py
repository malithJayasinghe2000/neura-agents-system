"""FiveNeurals' admins, and the shop facts they may read. ADR-0061.

An admin is **the first person in this system who reaches every shop**, so two
things are true here and nowhere else:

* **Who is an admin is a table changed only by command** (``platform_admins``):
  no route writes it, so no admin can make another from the dashboard.
* **What an admin reads across shops comes only from two database functions**,
  ``neura_admin_shops()`` and ``neura_admin_usage()``, whose owning role holds
  column grants on the shop facts of ADR-0061 §1 and nothing else, and which
  answer only a transaction opened for a live admin. So even a bug cannot hand an
  admin page a shopper's chat: the database has nothing of the kind to give it.

The sessions here are :meth:`~neura_core.db.Database.identity_session`, opened
**with** the admin's user id, already proved by the session cookie: the
functions read ``app.user_id`` and return nothing without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import ids
from neura_core.identity.schema import platform_admins, users
from neura_core.logging import get_logger

log = get_logger(__name__)

#: How recent an admin's sign-in must be (R22). Shop screens keep the usual
#: 30 days; an admin, who reaches every shop, signs in again after 12 hours.
ADMIN_FRESH = timedelta(hours=12)

_ADMINS = platform_admins.c


def fresh_enough(issued_at: datetime, *, now: datetime | None = None) -> bool:
    """Was this sign-in recent enough for an admin page?"""
    return (now or datetime.now(UTC)) - issued_at < ADMIN_FRESH


@dataclass(frozen=True, slots=True)
class Admin:
    email: str
    added_at: datetime


@dataclass(frozen=True, slots=True)
class AdminAdded:
    user_id: str
    #: The email had no account, and one was made, so the admin can sign in.
    made_account: bool
    #: They were an admin already; nothing changed.
    already: bool


@dataclass(frozen=True, slots=True)
class ShopFacts:
    """One shop as an admin sees it: facts, never a shopper (ADR-0061 §1)."""

    tenant_id: str
    name: str
    status: str
    #: ``config.mode`` as stored; ``None`` when the shop never set one.
    mode: str | None
    assistants: tuple[str, ...]
    website: str | None
    created_at: datetime
    connected: bool
    #: The Owners' emails, the shop's own contact.
    owners: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UsageFacts:
    """One shop's AI use for one assistant over a period: counts only."""

    tenant_id: str
    agent_key: str
    conversations: int
    turns: int
    llm_calls: int
    escalations: int
    blocked: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


async def is_admin(session: AsyncSession, user_id: str) -> bool:
    """Is this person a live admin? Read on every admin request."""
    if not user_id:
        return False
    found = await session.scalar(
        select(_ADMINS.user_id).where(_ADMINS.user_id == user_id, _ADMINS.removed_at.is_(None))
    )
    return found is not None


async def add_admin(session: AsyncSession, *, email: str) -> AdminAdded:
    """Make ``email`` an admin, making its account when it has none.

    A removed admin added again is live again; a live one is left as it is.
    """
    made = (
        await session.execute(
            pg_insert(users)
            .values(id=ids.new_id(ids.USER), email=email, name="")
            .on_conflict_do_nothing(index_elements=[users.c.email])
            .returning(users.c.id)
        )
    ).first()
    user_id = (
        str(made[0])
        if made
        else str(await session.scalar(select(users.c.id).where(users.c.email == email)))
    )
    already = await is_admin(session, user_id)
    if not already:
        statement = pg_insert(platform_admins).values(user_id=user_id)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[_ADMINS.user_id],
                set_={"added_at": statement.excluded.added_at, "removed_at": None},
            )
        )
        log.info("admin_added", user_id=user_id)
    return AdminAdded(user_id=user_id, made_account=bool(made), already=already)


async def remove_admin(session: AsyncSession, *, email: str) -> bool:
    """Stop ``email`` being an admin. ``False`` when they were not one."""
    user_id = await session.scalar(select(users.c.id).where(users.c.email == email))
    if user_id is None:
        return False
    removed = (
        await session.execute(
            update(platform_admins)
            .where(_ADMINS.user_id == str(user_id), _ADMINS.removed_at.is_(None))
            .values(removed_at=datetime.now(UTC))
            .returning(_ADMINS.user_id)
        )
    ).first()
    if removed is not None:
        log.info("admin_removed", user_id=str(user_id))
    return removed is not None


async def list_admins(session: AsyncSession) -> list[Admin]:
    """The live admins, the first added first."""
    rows = (
        await session.execute(
            select(users.c.email, _ADMINS.added_at)
            .select_from(platform_admins.join(users, users.c.id == _ADMINS.user_id))
            .where(_ADMINS.removed_at.is_(None))
            .order_by(_ADMINS.added_at)
        )
    ).all()
    return [Admin(email=str(row.email), added_at=row.added_at) for row in rows]


async def admin_shops(session: AsyncSession) -> list[ShopFacts]:
    """Every shop's facts, waiting shops first, then the newest. Empty for a non-admin."""
    rows = (await session.execute(text("SELECT * FROM neura_admin_shops()"))).all()
    return [
        ShopFacts(
            tenant_id=str(row.tenant_id),
            name=str(row.name),
            status=str(row.status),
            mode=row.mode,
            assistants=tuple(sorted(row.enabled_agents or ())),
            website=row.website,
            created_at=row.created_at,
            connected=bool(row.connected),
            owners=tuple(row.owners or ()),
        )
        for row in rows
    ]


async def admin_usage(session: AsyncSession, *, since: date, until: date) -> list[UsageFacts]:
    """AI use per shop and assistant, from ``since`` to ``until`` (both days counted)."""
    rows = (
        await session.execute(
            text("SELECT * FROM neura_admin_usage(:since, :until)"),
            {"since": since, "until": until},
        )
    ).all()
    return [
        UsageFacts(
            tenant_id=str(row.tenant_id),
            agent_key=str(row.agent_key),
            conversations=int(row.conversations or 0),
            turns=int(row.turns or 0),
            llm_calls=int(row.llm_calls or 0),
            escalations=int(row.escalations or 0),
            blocked=int(row.blocked or 0),
            prompt_tokens=int(row.prompt_tokens or 0),
            completion_tokens=int(row.completion_tokens or 0),
            cost_usd=Decimal(row.cost_usd or 0),
        )
        for row in rows
    ]


__all__ = [
    "ADMIN_FRESH",
    "Admin",
    "AdminAdded",
    "ShopFacts",
    "UsageFacts",
    "add_admin",
    "admin_shops",
    "admin_usage",
    "fresh_enough",
    "is_admin",
    "list_admins",
    "remove_admin",
]
