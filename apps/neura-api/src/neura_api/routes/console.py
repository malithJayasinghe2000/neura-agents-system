"""Signing a human into the merchant console. ADR-0026.

The console's entire authentication surface is these six endpoints, and they
are the only ones in this API that authenticate a **person** rather than a
program. Every other route resolves a bearer token to a tenant; these resolve a
cookie to a human, then a human to the merchants they may act for.

## The rule the rest of the console rests on

> **No tenant API key ever reaches the browser.**

The shortcut anyone in a hurry will propose is to mint a key at sign-in and let
the console call the existing API with it. That key carries the tenant's full
machine authority, has no session lifetime, and would live in every browser
extension, crash report and screenshot the merchant ever takes. The cookie here
grants *no* authority by itself: it names a person, and `memberships` decides the
rest, freshly, on every request (`AGENTS.md` rule 3).

## Why sign-in always answers the same thing

``POST /auth/request-link`` returns an identical response for an address with an
account and one without. *"No account with that email"* is an oracle: walk a
list of shop owners' addresses through it and you have a customer list and a
target list at once.

**That also means it cannot report a mail failure to the person waiting.** If
SMTP is down they see "check your inbox" and nothing arrives — which is why
`neura_core.email` distinguishes *sent*, *skipped* and *failed* and this module
logs which. The screen cannot say it; the log must.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.dependencies import DatabaseDep
from neura_api.envelopes import envelope
from neura_core import Database, get_logger, get_settings
from neura_core.email import Mailer
from neura_core.identity import (
    COOKIE_NAME,
    SESSION_TTL,
    issue,
    memberships_for,
    redeem,
    request_sign_in_link,
    role_may,
    verify,
)
from neura_core.identity.people import PeopleRepository
from neura_core.tenancy import TenantRepository

log = get_logger(__name__)

router = APIRouter(prefix="/console", tags=["console"])

#: What the merchant is told after asking for a link — the same words whether or
#: not the address has an account. Deliberately phrased so it is not a lie in
#: either case: it describes what *we* did, not what will arrive.
SENT_MESSAGE = "If that address has an account, a sign-in link is on its way."

SIGN_IN_SUBJECT = "Your FiveNeurals sign-in link"

#: What a refused invite link says, whatever was wrong with it: unknown, used,
#: cancelled, sent again, run out, or naming another shop (ADR-0058 §4). It
#: cannot say which, so it gives both next steps: someone who already joined
#: signs in (the link works once); anyone else asks the owner (G96).
INVITE_NO_LONGER_VALID = (
    "That invite link has already been used, or it no longer works. "
    "If you already joined, sign in. If not, ask the shop's owner to send it again."
)


def _sign_in_body(url: str, minutes: int) -> str:
    """Plain text, and short.

    No HTML and no images: a login mail is the one most likely to be filtered,
    and a filtered login mail reads to a merchant as a broken product. The
    warning at the end is there because this link *is* a credential — anyone
    holding it is signed in as them.
    """
    return (
        "Hello,\n\n"
        "Use the link below to sign in to your FiveNeurals console.\n\n"
        f"{url}\n\n"
        f"It works once and expires in {minutes} minutes.\n\n"
        "If you did not ask to sign in, you can ignore this email — "
        "the link is useless without this inbox, and nothing has changed.\n"
    )


class RequestLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Validated as an address before it reaches a query, so a malformed value
    #: is a 422 rather than a lookup that quietly matches nothing.
    email: EmailStr


class VerifyLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)


class AcceptInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The shop the link names. A suggestion, like every id a browser sends: the
    #: token is looked up in that shop's own session, so a wrong shop finds nothing.
    shop: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    token: str = Field(min_length=1, max_length=512)


@router.post("/auth/request-link", summary="Email a one-time sign-in link")
async def request_link(body: RequestLink, request: Request, db: DatabaseDep) -> dict[str, object]:
    settings = get_settings()

    # No `app.tenant_id` and no user id: the person has proved nothing yet, and
    # this call is what begins to change that. The transaction can see `users`
    # and `login_tokens` and nothing belonging to any merchant.
    async with db.identity_session() as session:
        minted = await request_sign_in_link(
            session,
            email=str(body.email),
            console_base_url=settings.console_base_url,
            requested_ip=_peer(request),
        )

    if minted.minted:
        result = Mailer(settings).send(
            to=str(body.email),
            subject=SIGN_IN_SUBJECT,
            body=_sign_in_body(minted.url, minutes=15),
        )
        # The person is told "check your inbox" regardless, so this log line is
        # the only place a delivery failure is visible at all.
        if not result.sent:
            log.error(
                "sign_in_mail_not_delivered",
                user_id=minted.user_id,
                skipped=result.skipped,
                error=result.error,
            )

    return envelope({"message": SENT_MESSAGE})


@router.post("/auth/verify", summary="Redeem a sign-in link and start a session")
async def verify_link(
    body: VerifyLink, response: Response, request: Request, db: DatabaseDep
) -> dict[str, object]:
    async with db.identity_session() as session:
        user_id = await redeem(session, token=body.token)

    if not user_id:
        # One message for unknown, expired, already-used and malformed. Telling
        # the holder of a stolen link *which* it was tells them whether it ever
        # worked.
        log.info("console_sign_in_failed", ip=_peer(request))
        return envelope({"signed_in": False, "message": "That link is no longer valid."})

    _set_session_cookie(response, issue(user_id, get_settings().secret_key))
    log.info("console_signed_in", user_id=user_id)
    return envelope({"signed_in": True})


@router.post("/auth/accept-invite", summary="Use an invite link: join the shop")
async def accept_invite(
    body: AcceptInvite,
    response: Response,
    request: Request,
    db: DatabaseDep,
    session_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> dict[str, object]:
    """ADR-0058 §4: the link adds the person to **that shop only**, with the
    invite's role, making their account when the email has none. Used once; the
    audit entry is written in the same transaction.

    **It signs in only a brand-new account** (R13, the owner, 2026-10-10;
    ADR-0059). A session opens every shop a person is in, so for someone who
    already has an account the link would be a 7-day sign-in to their other shops
    too, for whoever the email was forwarded to. So they are added, and sign in
    as usual; someone already signed in as that very person goes straight in,
    and a browser signed in as somebody else is left as it is. A new account is
    signed in wherever the link is opened: the link is its only way in.
    """
    async with db.tenant_session(body.shop) as session:
        joined = await PeopleRepository(session).accept(body.shop, token=body.token)
        shop_name = None
        if joined is not None:
            tenant = await TenantRepository(session).get(body.shop)
            shop_name = tenant.name if tenant else None
            await PostgresAuditLog(session).record(
                AuditEntry(
                    tenant_id=body.shop,
                    event_type=AuditEvent.PEOPLE_CHANGE,
                    actor=joined.user_id,
                    outcome="invite.accepted",
                    payload={
                        "invite_id": joined.invite_id,
                        "role": joined.role,
                        "new_account": joined.made_account,
                    },
                )
            )

    if joined is None:
        log.info("console_invite_failed", ip=_peer(request))
        return envelope({"signed_in": False, "message": INVITE_NO_LONGER_VALID})

    log.info("console_invite_accepted", user_id=joined.user_id, tenant_id=body.shop)
    secret = get_settings().secret_key
    already = verify(session_cookie or "", secret)
    if joined.made_account:
        _set_session_cookie(response, issue(joined.user_id, secret))
    elif already is None or already.user_id != joined.user_id:
        return envelope(
            {
                "signed_in": False,
                "joined": True,
                "tenant_id": body.shop,
                "message": f"You've joined {shop_name or 'the shop'}. Sign in to open it.",
            }
        )
    return envelope({"signed_in": True, "tenant_id": body.shop, "user_id": joined.user_id})


@router.get("/me", summary="Who is signed in, and which merchants they may act for")
async def me(
    request: Request,
    db: DatabaseDep,
    session_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> dict[str, object]:
    signed_in = verify(session_cookie or "", get_settings().secret_key)
    if signed_in is None:
        return envelope({"signed_in": False, "memberships": []})

    # Re-derived here rather than read from the cookie, which is the whole
    # reason the cookie carries nothing but a person: a revoked membership stops
    # working on this request, not when the cookie expires.
    async with db.identity_session(signed_in.user_id) as session:
        held = await memberships_for(session, signed_in.user_id)

    # Every permission some route declares, gathered at startup. What each role
    # holds of them is the map's answer, so the dashboard shows each person only
    # what they may open, and never keeps a copy of the map (ADR-0058 §1).
    known: frozenset[str] = getattr(request.app.state, "permissions", frozenset())
    memberships = []
    for m in held:
        name, assistants = await _shop(db, m.tenant_id)
        memberships.append(
            {
                "tenant_id": m.tenant_id,
                "role": m.role,
                "name": name,
                "assistants": assistants,
                "permissions": sorted(p for p in known if role_may(m.role, p)),
            }
        )
    return envelope({"signed_in": True, "user_id": signed_in.user_id, "memberships": memberships})


async def _shop(db: Database, tenant_id: str) -> tuple[str | None, list[str]]:
    """The shop's own name, and the assistants it has.

    **The name**, so a merchant never has to recognise ``tn_01M…``. ``None`` when
    there is no name to show; the screen falls back to the id rather than
    inventing one.

    **The assistants** are ``enabled_agents``, sorted, passed through as data:
    the console hides a screen that belongs to an assistant the shop does not
    have (a shop with NEURA-CARE only is not shown *Sold out*). This module still
    names no agent — it hands over a list it does not read. **Display only**:
    every agent's own routes check the entitlement themselves.

    ``tenants`` is tenant-scoped and the identity session names no tenant, so
    both are read in that shop's own session — and only for a membership just
    proved above, which is what stops this being a way to read another
    merchant's details.
    """
    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).get(tenant_id)
    if tenant is None:
        return None, []
    return (tenant.name or None), sorted(tenant.enabled_agents)


@router.post("/auth/sign-out", summary="End the session")
async def sign_out(response: Response) -> dict[str, object]:
    """Clears the cookie.

    There is no server-side session to destroy ([ADR-0026](../../../../docs/architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md)),
    and that is only acceptable because the cookie grants no authority on its
    own. **Removing a membership is what actually revokes access**, and it takes
    effect on the next request rather than waiting for any cookie to expire.
    """
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    return envelope({"signed_out": True})


def _set_session_cookie(response: Response, value: str) -> None:
    """Every flag here is doing a job.

    ``httponly`` keeps the cookie out of reach of any script that gets onto the
    page — the reason it is a cookie rather than a token in local storage.
    ``secure`` and ``path="/"`` with no domain are *required* by the ``__Host-``
    prefix, which the browser enforces, and which stops a sibling subdomain from
    setting or overwriting the session. ``samesite="lax"`` still allows the
    top-level navigation from the email link, while refusing the cookie on
    cross-site form posts.
    """
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _peer(request: Request) -> str:
    """The network peer, for abuse investigation only.

    Never `X-Forwarded-For` unless a proxy hop count is configured — trusting a
    header the caller writes makes the record a fiction (ADR-0017).
    """
    return request.client.host if request.client else ""
