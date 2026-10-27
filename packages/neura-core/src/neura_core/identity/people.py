"""The people in a shop: invites, roles, removal. ADR-0058 §3 to §5.

Everything here runs in the shop's own :meth:`~neura_core.db.Database.tenant_session`,
so ``memberships`` and ``membership_invites`` answer only for that shop, and Shop
A's Owner can never invite anyone into Shop B (§5): the row would fail the
policy's ``WITH CHECK``. ``users`` has no ``tenant_id`` (ADR-0026 §4) and is read
and written in the same transaction, for the email and the name.

## A shop always keeps at least one Owner (§3)

Removing a person and changing a role both start by **locking the shop's live
Owner rows** (``SELECT … FOR UPDATE``), then decide, then write, in one
transaction. Two Owners removing each other at the same moment: the second waits
for the first, then reads one Owner, and is refused. Checking and writing in two
steps would let both pass, and leave a shop nobody can run.

The person doing it is checked again **under the same lock**: an Owner removed a
moment ago, whose request had already passed the door, is refused here rather
than allowed one last change.

## The invite link (§4)

Works **once**, for **7 days**; only its SHA-256 is stored, as a sign-in link's
is. *Send again* writes a new hash over the old one, so the old link stops; a
second invite to the same email does the same. Accepting marks it used in the
statement that checks it is unused, and in the same transaction makes the
account (when the email has none) and the membership, so a forwarded link has
exactly one winner.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import Row, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import ids
from neura_core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from neura_core.identity.login import fingerprint
from neura_core.identity.roles import PEOPLE_WRITE, ROLE_NOT_ALLOWED, Role, role_may
from neura_core.identity.schema import membership_invites, memberships, users
from neura_core.logging import get_logger

log = get_logger(__name__)

#: How long an invite link works (R9, the owner: 7 days).
INVITE_TTL = timedelta(days=7)

#: Bytes of entropy in an invite token: the same 256 bits as a sign-in link.
_ENTROPY_BYTES = 32

_INVITES = membership_invites.c
_MEMBERS = memberships.c
_OPEN = (_INVITES.accepted_at.is_(None), _INVITES.cancelled_at.is_(None))


@dataclass(frozen=True, slots=True)
class Member:
    """One person who can open the shop's dashboard now."""

    user_id: str
    email: str
    name: str
    role: str
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class Invite:
    """An invite not yet accepted or cancelled. It may have run out."""

    id: str
    email: str
    role: str
    sent_at: datetime
    expires_at: datetime
    #: The Owner who sent it, or last sent it again.
    invited_by: str = ""

    def expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class SentInvite:
    """An invite and its link. ``token`` and ``url`` exist only to be emailed:
    never stored, never logged, never returned to the Owner's browser."""

    invite: Invite
    token: str
    url: str


@dataclass(frozen=True, slots=True)
class Joined:
    """What accepting an invite did."""

    user_id: str
    role: str
    invite_id: str
    #: The email had no account, and one was made.
    made_account: bool


@dataclass(frozen=True, slots=True)
class Person:
    """Who made something, as Shop connection names them (*Made … by …*)."""

    #: Their name, or their email when they never gave one.
    name: str
    #: Their role in the shop now; ``None`` when they are no longer in it.
    role: str | None


def known_role(role: str) -> str:
    """``role`` if it is one of the three, or a plain refusal."""
    try:
        return Role(role).value
    except ValueError:
        raise ValidationError(
            "Unknown role.", details={"role": role, "expected": [r.value for r in Role]}
        ) from None


def invite_url(console_base_url: str, tenant_id: str, token: str) -> str:
    """The link the email carries. It names the shop, so accepting it can look
    the token up in that shop's own session (module docstring)."""
    query = urlencode({"shop": tenant_id, "token": token})
    return f"{console_base_url.rstrip('/')}/auth/invite?{query}"


class PeopleRepository:
    """People and invites for one shop, inside the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def members(self, tenant_id: str) -> list[Member]:
        """Everyone who can open the shop now, the first to join first."""
        rows = (
            await self._session.execute(
                select(
                    _MEMBERS.user_id,
                    _MEMBERS.role,
                    _MEMBERS.created_at,
                    users.c.email,
                    users.c.name,
                )
                .select_from(memberships.join(users, users.c.id == _MEMBERS.user_id))
                .where(_MEMBERS.tenant_id == tenant_id, _MEMBERS.revoked_at.is_(None))
                .order_by(_MEMBERS.created_at, _MEMBERS.user_id)
            )
        ).all()
        return [
            Member(
                user_id=str(row.user_id),
                email=str(row.email),
                name=str(row.name or ""),
                role=str(row.role),
                joined_at=row.created_at,
            )
            for row in rows
        ]

    async def invites(self, tenant_id: str) -> list[Invite]:
        """Invites not accepted or cancelled, including ones that ran out: the
        Owner sees them and may send them again."""
        rows = (
            await self._session.execute(
                select(membership_invites)
                .where(_INVITES.tenant_id == tenant_id, *_OPEN)
                .order_by(_INVITES.sent_at, _INVITES.id)
            )
        ).all()
        return [_invite(row) for row in rows]

    async def invite(
        self,
        tenant_id: str,
        *,
        email: str,
        role: str,
        by: str,
        console_base_url: str,
        now: datetime | None = None,
    ) -> SentInvite:
        """Invite ``email`` with ``role``, or replace the invite already waiting for it.

        Refused for someone already in the shop, with a plain sentence (§4). The
        answer is otherwise the same whether or not the email has an account
        anywhere in NEURA, so an Owner cannot use this to find out who does.
        """
        wanted = known_role(role)
        moment = now or datetime.now(UTC)

        member = await self._session.scalar(
            select(_MEMBERS.id)
            .select_from(memberships.join(users, users.c.id == _MEMBERS.user_id))
            .where(
                _MEMBERS.tenant_id == tenant_id,
                _MEMBERS.revoked_at.is_(None),
                users.c.email == email,
            )
        )
        if member is not None:
            raise ConflictError("That person is already in this shop.", code="ALREADY_A_MEMBER")

        token = secrets.token_urlsafe(_ENTROPY_BYTES)
        statement = pg_insert(membership_invites).values(
            id=ids.new_id(ids.INVITE),
            tenant_id=tenant_id,
            email=email,
            role=wanted,
            token_hash=fingerprint(token),
            invited_by=by,
            sent_at=moment,
            expires_at=moment + INVITE_TTL,
        )
        row = (
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[_INVITES.tenant_id, _INVITES.email],
                    index_where=text("accepted_at IS NULL AND cancelled_at IS NULL"),
                    set_={
                        "role": statement.excluded.role,
                        "token_hash": statement.excluded.token_hash,
                        "invited_by": statement.excluded.invited_by,
                        "sent_at": statement.excluded.sent_at,
                        "expires_at": statement.excluded.expires_at,
                    },
                ).returning(membership_invites)
            )
        ).one()
        log.info("invite_sent", tenant_id=tenant_id, invite_id=row.id, by=by)
        return SentInvite(
            invite=_invite(row), token=token, url=invite_url(console_base_url, tenant_id, token)
        )

    async def send_again(
        self,
        tenant_id: str,
        invite_id: str,
        *,
        by: str,
        console_base_url: str,
        now: datetime | None = None,
    ) -> SentInvite:
        """A new link for a waiting invite, for 7 more days. The old link stops."""
        moment = now or datetime.now(UTC)
        token = secrets.token_urlsafe(_ENTROPY_BYTES)
        row = (
            await self._session.execute(
                update(membership_invites)
                .where(_INVITES.tenant_id == tenant_id, _INVITES.id == invite_id, *_OPEN)
                .values(
                    token_hash=fingerprint(token),
                    invited_by=by,
                    sent_at=moment,
                    expires_at=moment + INVITE_TTL,
                )
                .returning(membership_invites)
            )
        ).first()
        if row is None:
            raise NotFoundError("No such invite.", details={"invite_id": invite_id})
        log.info("invite_sent_again", tenant_id=tenant_id, invite_id=invite_id, by=by)
        return SentInvite(
            invite=_invite(row), token=token, url=invite_url(console_base_url, tenant_id, token)
        )

    async def cancel(
        self, tenant_id: str, invite_id: str, *, now: datetime | None = None
    ) -> Invite:
        """Stop a waiting invite. Its link stops at once."""
        row = (
            await self._session.execute(
                update(membership_invites)
                .where(_INVITES.tenant_id == tenant_id, _INVITES.id == invite_id, *_OPEN)
                .values(cancelled_at=now or datetime.now(UTC))
                .returning(membership_invites)
            )
        ).first()
        if row is None:
            raise NotFoundError("No such invite.", details={"invite_id": invite_id})
        return _invite(row)

    async def accept(
        self, tenant_id: str, *, token: str, now: datetime | None = None
    ) -> Joined | None:
        """Use an invite link. ``None`` for every kind of failure, alike.

        Unknown, used, cancelled, sent again, run out, or a link naming another
        shop: one answer, so whoever holds a stolen link learns nothing from it.
        A person already in the shop keeps the role they have: an invite never
        changes a member's role, which only an Owner does, under the Owner rule.
        """
        if not token:
            return None
        moment = now or datetime.now(UTC)

        used = (
            await self._session.execute(
                update(membership_invites)
                .where(
                    _INVITES.tenant_id == tenant_id,
                    _INVITES.token_hash == fingerprint(token),
                    _INVITES.expires_at > moment,
                    *_OPEN,
                )
                .values(accepted_at=moment)
                .returning(_INVITES.id, _INVITES.email, _INVITES.role)
            )
        ).first()
        if used is None:
            log.info("invite_rejected", tenant_id=tenant_id)
            return None

        made = (
            await self._session.execute(
                pg_insert(users)
                .values(id=ids.new_id(ids.USER), email=used.email, name="", last_seen_at=moment)
                .on_conflict_do_nothing(index_elements=[users.c.email])
                .returning(users.c.id)
            )
        ).first()
        user_id = (
            str(made[0])
            if made
            else str(
                await self._session.scalar(select(users.c.id).where(users.c.email == used.email))
            )
        )

        statement = pg_insert(memberships).values(
            id=ids.new_id(ids.MEMBERSHIP),
            tenant_id=tenant_id,
            user_id=user_id,
            role=used.role,
            created_at=moment,
        )
        # Someone removed earlier comes back with the invite's role, joined now.
        # Someone already in keeps theirs: the `WHERE` leaves an active row alone.
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[_MEMBERS.tenant_id, _MEMBERS.user_id],
                set_={
                    "role": statement.excluded.role,
                    "revoked_at": None,
                    "created_at": statement.excluded.created_at,
                },
                where=_MEMBERS.revoked_at.is_not(None),
            )
        )
        role = await self._session.scalar(
            select(_MEMBERS.role).where(
                _MEMBERS.tenant_id == tenant_id,
                _MEMBERS.user_id == user_id,
                _MEMBERS.revoked_at.is_(None),
            )
        )
        await self._session.execute(
            update(membership_invites).where(_INVITES.id == used.id).values(accepted_by=user_id)
        )
        if not made:
            await self._session.execute(
                update(users).where(users.c.id == user_id).values(last_seen_at=moment)
            )
        log.info("invite_accepted", tenant_id=tenant_id, invite_id=used.id, user_id=user_id)
        return Joined(
            user_id=user_id, role=str(role), invite_id=str(used.id), made_account=bool(made)
        )

    async def change_role(self, tenant_id: str, user_id: str, *, role: str, by: str) -> str:
        """Give a person another role. Returns the role they had.

        Refused when it would leave the shop with no Owner (§3).
        """
        wanted = known_role(role)
        owners = await self._lock_owners(tenant_id)
        await self._still_allowed(tenant_id, by)
        current = await self._current(tenant_id, user_id)
        if current == Role.OWNER and wanted != Role.OWNER and owners <= {user_id}:
            raise _last_owner()
        if current != wanted:
            await self._session.execute(
                update(memberships)
                .where(
                    _MEMBERS.tenant_id == tenant_id,
                    _MEMBERS.user_id == user_id,
                    _MEMBERS.revoked_at.is_(None),
                )
                .values(role=wanted)
            )
        return current

    async def remove(
        self, tenant_id: str, user_id: str, *, by: str, now: datetime | None = None
    ) -> str:
        """Take a person out of the shop. Returns the role they had.

        ``revoked_at``, never a delete: who used to have access is what an
        incident asks (ADR-0026 §4). It bites on their next request, because the
        cookie carries no access. Refused when it would leave no Owner (§3).
        """
        owners = await self._lock_owners(tenant_id)
        await self._still_allowed(tenant_id, by)
        current = await self._current(tenant_id, user_id)
        if current == Role.OWNER and owners <= {user_id}:
            raise _last_owner()
        await self._session.execute(
            update(memberships)
            .where(
                _MEMBERS.tenant_id == tenant_id,
                _MEMBERS.user_id == user_id,
                _MEMBERS.revoked_at.is_(None),
            )
            .values(revoked_at=now or datetime.now(UTC))
        )
        return current

    async def person(self, tenant_id: str, user_id: str | None) -> Person | None:
        """Who ``user_id`` is, for *Made [date] by [name]*. ``None`` for nobody."""
        if not user_id:
            return None
        row = (
            await self._session.execute(
                select(users.c.name, users.c.email).where(users.c.id == user_id)
            )
        ).first()
        if row is None:
            return None
        role = await self._session.scalar(
            select(_MEMBERS.role).where(
                _MEMBERS.tenant_id == tenant_id,
                _MEMBERS.user_id == user_id,
                _MEMBERS.revoked_at.is_(None),
            )
        )
        return Person(name=str(row.name or row.email), role=str(role) if role else None)

    async def _lock_owners(self, tenant_id: str) -> set[str]:
        """The shop's live Owners, locked until the transaction ends."""
        rows = await self._session.execute(
            select(_MEMBERS.user_id)
            .where(
                _MEMBERS.tenant_id == tenant_id,
                _MEMBERS.role == Role.OWNER.value,
                _MEMBERS.revoked_at.is_(None),
            )
            .with_for_update()
        )
        return {str(user) for user in rows.scalars()}

    async def _still_allowed(self, tenant_id: str, by: str) -> None:
        """The person making the change may still do it, read under the lock."""
        role = await self._session.scalar(
            select(_MEMBERS.role).where(
                _MEMBERS.tenant_id == tenant_id,
                _MEMBERS.user_id == by,
                _MEMBERS.revoked_at.is_(None),
            )
        )
        if role is None or not role_may(str(role), PEOPLE_WRITE):
            raise ForbiddenError(
                "Your role in this shop doesn't include this. If you need it, ask the shop's owner.",
                code=ROLE_NOT_ALLOWED,
                details={"role": role, "permission": PEOPLE_WRITE},
            )

    async def _current(self, tenant_id: str, user_id: str) -> str:
        role = await self._session.scalar(
            select(_MEMBERS.role)
            .where(
                _MEMBERS.tenant_id == tenant_id,
                _MEMBERS.user_id == user_id,
                _MEMBERS.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if role is None:
            raise NotFoundError("No such person in this shop.", details={"user_id": user_id})
        return str(role)


def _last_owner() -> ConflictError:
    return ConflictError(
        "A shop always keeps at least one Owner. Make someone else an Owner first.",
        code="LAST_OWNER",
    )


def _invite(row: Row[Any]) -> Invite:
    return Invite(
        id=str(row.id),
        email=str(row.email),
        role=str(row.role),
        sent_at=row.sent_at,
        expires_at=row.expires_at,
        invited_by=str(row.invited_by),
    )


__all__ = [
    "INVITE_TTL",
    "Invite",
    "Joined",
    "Member",
    "PeopleRepository",
    "Person",
    "SentInvite",
    "invite_url",
    "known_role",
]
