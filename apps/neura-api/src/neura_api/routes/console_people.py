"""People: who can open a shop's dashboard, and with which role. ADR-0058 §3 to §5.

    GET    /v1/console/shops/{tenant_id}/people                         members and waiting invites
    POST   /v1/console/shops/{tenant_id}/invites                        invite an email with a role
    POST   /v1/console/shops/{tenant_id}/invites/{invite_id}/send-again a new link; the old one stops
    DELETE /v1/console/shops/{tenant_id}/invites/{invite_id}            cancel it
    PUT    /v1/console/shops/{tenant_id}/people/{user_id}               change a role
    DELETE /v1/console/shops/{tenant_id}/people/{user_id}               remove a person

**The Owner's alone** (``people:members:write``): who works in a shop is the
owner's business, and a list of colleagues' emails is personal data (§4).

**The rules are in** ``neura_core.identity.people``, inside the shop's own
transaction: a shop always keeps one Owner, also when two Owners act at once; a
member cannot be invited again; Shop A cannot invite into Shop B. This module
adds the email and the audit entry, **in the same transaction as the change**,
so a change is never made without its record.

**The link is never returned to the browser.** It is emailed, and nothing else:
the Owner sees *Invite sent*, and whether the email could be sent. On a computer
with no mail server, ``make invite-link`` prints one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_core import get_logger, get_settings
from neura_core.email import Mailer
from neura_core.identity.people import Invite, PeopleRepository, SentInvite
from neura_core.identity.roles import PEOPLE_WRITE, Role
from neura_core.tenancy import TenantRepository

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: The invite email's subject. ``{shop}`` is the shop's own name.
INVITE_SUBJECT = "You're invited to {shop} on FiveNeurals"

#: What each role can do, said in the invite email. The People screen's cards,
#: in a sentence each (console.md §3.8).
ROLE_LINES: dict[str, str] = {
    Role.OWNER: (
        "As an Owner you can do everything in the shop's dashboard, "
        "including inviting and removing people."
    ),
    Role.SUPPORT: "As Support you can read the shop's chats and grade replies in Review.",
    Role.DEVELOPER: (
        "As the Developer you can open Shop connection and Help: you connect the shop "
        "and make its secrets. You never see shoppers' chats."
    ),
}

ROLE_NAMES: dict[str, str] = {
    Role.OWNER: "Owner",
    Role.SUPPORT: "Support",
    Role.DEVELOPER: "Developer",
}


def invite_body(*, inviter: str, shop: str, role: str, url: str, until: datetime) -> str:
    """Plain text and short, as the sign-in email is (`routes/console.py`).

    The link is a credential for one shop's dashboard, so the email says it works
    once and when it stops, and that nothing happens if it is ignored.
    """
    return (
        "Hello,\n\n"
        f"{inviter} invited you to {shop}'s dashboard on FiveNeurals, "
        f"as {ROLE_NAMES[role]}.\n\n"
        f"{ROLE_LINES[role]}\n\n"
        "Use the link below to join:\n\n"
        f"{url}\n\n"
        f"It works once, until {_day(until)}.\n\n"
        "If you did not expect this email, you can ignore it. "
        "Nothing happens unless the link is used.\n"
    )


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: str = Field(min_length=1, max_length=32)


class RoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=32)


@router.get("/people", summary="Who can open this shop's dashboard, and the invites waiting")
async def people(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(PEOPLE_WRITE))],
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = PeopleRepository(session)
        members = await repository.members(actor.tenant_id)
        invites = await repository.invites(actor.tenant_id)

    now = datetime.now(UTC)
    return envelope(
        {
            "members": [
                {
                    "user_id": member.user_id,
                    "name": member.name,
                    "email": member.email,
                    "role": member.role,
                    "joined_at": member.joined_at.isoformat(),
                    "you": member.user_id == actor.user_id,
                }
                for member in members
            ],
            "invites": [_invite_payload(invite, now) for invite in invites],
            # Said by the server, so the screen need not count: *The only Owner,
            # so this can't be removed* rests on it.
            "owners": sum(1 for member in members if member.role == Role.OWNER),
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/invites", summary="Invite a person, by email, with a role")
async def send_invite(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(PEOPLE_WRITE))],
    body: InviteRequest,
) -> dict[str, Any]:
    settings = get_settings()
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = PeopleRepository(session)
        sent = await repository.invite(
            actor.tenant_id,
            email=str(body.email),
            role=body.role,
            by=actor.user_id,
            console_base_url=settings.console_base_url,
        )
        await _record(
            session, actor, "invite.sent", invite_id=sent.invite.id, role=sent.invite.role
        )
        words = await _words(session, actor, sent)

    emailed = _mail(sent, words)
    return envelope(
        {"invite": _invite_payload(sent.invite), "emailed": emailed},
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/invites/{invite_id}/send-again", summary="A new link; the old one stops")
async def send_again(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(PEOPLE_WRITE))],
    invite_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        sent = await PeopleRepository(session).send_again(
            actor.tenant_id,
            invite_id,
            by=actor.user_id,
            console_base_url=settings.console_base_url,
        )
        await _record(session, actor, "invite.sent_again", invite_id=sent.invite.id)
        words = await _words(session, actor, sent)

    emailed = _mail(sent, words)
    return envelope(
        {"invite": _invite_payload(sent.invite), "emailed": emailed},
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/invites/{invite_id}", summary="Cancel a waiting invite; its link stops")
async def cancel_invite(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(PEOPLE_WRITE))],
    invite_id: str,
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        cancelled = await PeopleRepository(session).cancel(actor.tenant_id, invite_id)
        await _record(session, actor, "invite.cancelled", invite_id=cancelled.id)
    return envelope({"cancelled": True}, request_id=getattr(request.state, "request_id", None))


@router.put("/people/{user_id}", summary="Give a person another role")
async def change_role(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(PEOPLE_WRITE))],
    user_id: str,
    body: RoleRequest,
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        before = await PeopleRepository(session).change_role(
            actor.tenant_id, user_id, role=body.role, by=actor.user_id
        )
        if before != body.role:
            await _record(
                session,
                actor,
                "member.role_changed",
                user_id=user_id,
                **{"from": before, "to": body.role},
            )
    return envelope(
        {"user_id": user_id, "role": body.role},
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/people/{user_id}", summary="Remove a person; it bites on their next click")
async def remove(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(PEOPLE_WRITE))],
    user_id: str,
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        role = await PeopleRepository(session).remove(actor.tenant_id, user_id, by=actor.user_id)
        await _record(session, actor, "member.removed", user_id=user_id, role=role)
    return envelope({"removed": True}, request_id=getattr(request.state, "request_id", None))


async def who_made(session: Any, tenant_id: str, user_id: str | None) -> dict[str, Any] | None:
    """*Made [date] by [name] ([role])* on Shop connection (ADR-0058 §6).

    The name, or the email of someone who never gave one; their role now, or
    ``null`` when they are no longer in the shop. ``None`` when nobody is
    recorded, as for a token made before this was kept: the screen then names
    nobody rather than guessing.
    """
    person = await PeopleRepository(session).person(tenant_id, user_id)
    if person is None:
        return None
    return {"name": person.name, "role": person.role}


async def _record(session: Any, actor: ConsoleActor, outcome: str, **payload: str) -> None:
    """One audit entry, who did it, and ids and roles: never an email."""
    await PostgresAuditLog(session).record(
        AuditEntry(
            tenant_id=actor.tenant_id,
            event_type=AuditEvent.PEOPLE_CHANGE,
            actor=actor.user_id,
            outcome=outcome,
            payload=payload,
        )
    )


async def _words(session: Any, actor: ConsoleActor, sent: SentInvite) -> tuple[str, str]:
    """The email's subject and body, with the shop's and the inviter's names."""
    tenant = await TenantRepository(session).get(actor.tenant_id)
    inviter = await PeopleRepository(session).person(actor.tenant_id, actor.user_id)
    shop = (tenant.name if tenant else "") or "a shop"
    return (
        INVITE_SUBJECT.format(shop=shop),
        invite_body(
            inviter=inviter.name if inviter else "Someone",
            shop=shop,
            role=sent.invite.role,
            url=sent.url,
            until=sent.invite.expires_at,
        ),
    )


def _mail(sent: SentInvite, words: tuple[str, str]) -> bool:
    """Send it, after the transaction: an invite whose row was rolled back must
    not be in anybody's inbox. Whether it went is said to the Owner, who is
    signed in and learns nothing about anybody else from it."""
    subject, body = words
    result = Mailer(get_settings()).send(to=sent.invite.email, subject=subject, body=body)
    if not result.sent:
        log.error(
            "invite_mail_not_delivered",
            invite_id=sent.invite.id,
            skipped=result.skipped,
            error=result.error,
        )
    return result.sent


def _invite_payload(invite: Invite, now: datetime | None = None) -> dict[str, Any]:
    return {
        "id": invite.id,
        "email": invite.email,
        "role": invite.role,
        "sent_at": invite.sent_at.isoformat(),
        "expires_at": invite.expires_at.isoformat(),
        "expired": invite.expired(now),
    }


def _day(moment: datetime) -> str:
    """*October 17, 2026*: a date, because a time would need a time zone."""
    return f"{moment:%B} {moment.day}, {moment.year}"


__all__ = ["INVITE_SUBJECT", "ROLE_LINES", "invite_body", "router", "who_made"]
