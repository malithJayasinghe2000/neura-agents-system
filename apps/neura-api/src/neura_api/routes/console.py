"""Signing a human into the merchant console. ADR-0026.

The console's entire authentication surface is these five endpoints, and they
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

from neura_api.dependencies import DatabaseDep
from neura_api.envelopes import envelope
from neura_core import get_logger, get_settings
from neura_core.email import Mailer
from neura_core.identity import (
    COOKIE_NAME,
    SESSION_TTL,
    issue,
    memberships_for,
    redeem,
    request_sign_in_link,
    verify,
)

log = get_logger(__name__)

router = APIRouter(prefix="/console", tags=["console"])

#: What the merchant is told after asking for a link — the same words whether or
#: not the address has an account. Deliberately phrased so it is not a lie in
#: either case: it describes what *we* did, not what will arrive.
SENT_MESSAGE = "If that address has an account, a sign-in link is on its way."

SIGN_IN_SUBJECT = "Your FiveNeurals sign-in link"


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


@router.get("/me", summary="Who is signed in, and which merchants they may act for")
async def me(
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

    return envelope(
        {
            "signed_in": True,
            "user_id": signed_in.user_id,
            "memberships": [{"tenant_id": m.tenant_id, "role": m.role} for m in held],
        }
    )


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
