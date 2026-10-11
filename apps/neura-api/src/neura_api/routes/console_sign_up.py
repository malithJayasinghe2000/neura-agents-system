"""A new shop signs up. ADR-0058 §7, R14 to R17.

Two routes before there is a person or a shop, and the three emails of sign up:

* ``POST /auth/sign-up`` checks the form, counts the request against the same
  limit as sign-in (G97), stores the request and mails a link. **The same words
  for every email**, and every email gets a link (R15), so the form says nothing
  about who has an account (console.md §4.3 rule 4).
* ``POST /auth/confirm-sign-up`` uses the link: the account, a shop **waiting**
  for approval, its Owner, an audit entry, and the session cookie.

The approval and refusal emails are sent by FiveNeurals' command
(``scripts/tenant_admin.py``); their words live here, beside the confirm email,
so every email of sign up is read in one place.

## Why the confirm email never names the shop

Anyone can type anything into the form, for any address. An email that repeated
the shop's name or website would let anyone make NEURA mail any text they like
to a stranger, from NEURA's own address. It says only that someone asked.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.dependencies import DatabaseDep
from neura_api.envelopes import envelope
from neura_api.routes.console import limit_links, peer, set_session_cookie
from neura_core import get_logger, get_settings, ids
from neura_core.email import Mailer
from neura_core.identity import issue
from neura_core.identity.sign_up import (
    SIGN_UP_TTL,
    confirm_sign_up,
    request_sign_up,
    shop_name,
    shop_website,
)

log = get_logger(__name__)

router = APIRouter(prefix="/console", tags=["console"])

#: What the form is told, the same for every email.
SENT_MESSAGE = "A link is on its way. It works once and expires in 15 minutes."

#: What someone who asked for too many links is told (R17 c). Counted with
#: sign-in's requests: the limit is on the emails one inbox gets.
SIGN_UP_LIMITED = "Too many sign-up links were asked for. Please wait a while, then try again."

#: What a used, replaced or old link says, whatever was wrong with it (R17 b).
NO_LONGER_VALID = (
    "Sign-up links expire after 15 minutes and work once. "
    "If you already confirmed, sign in. If not, create your account again."
)

CONFIRM_SUBJECT = "Confirm your FiveNeurals sign-up"

#: The owner guide, named by the approval email and the waiting screen.
OWNER_GUIDE_URL = "https://neura.fiveneurals.com/docs/owners/"


def confirm_body(url: str) -> str:
    """The confirm email (R17, the owner: A). Plain text, as the sign-in email is.

    It takes the link and nothing else, so nothing typed into the form can
    reach it (module docstring).
    """
    minutes = int(SIGN_UP_TTL.total_seconds() // 60)
    return (
        "Hello,\n\n"
        "Someone asked to sign up a shop for FiveNeurals with this email address. "
        "If it was you, use the link below to confirm it.\n\n"
        f"{url}\n\n"
        f"It works once and expires in {minutes} minutes.\n\n"
        "If it was not you, you can ignore this email. Nothing has been made.\n"
    )


def approved_email(*, shop: str, dashboard: str) -> tuple[str, str]:
    """The approval email: subject and body (R17, the owner: A).

    It names the shop: by now a person at FiveNeurals has looked at it.
    """
    return (
        f"{shop} is ready on FiveNeurals",
        "Hello,\n\n"
        f"FiveNeurals has approved {shop}. Sign in to start:\n\n"
        f"{dashboard}\n\n"
        "Your assistant starts in practice mode, so shoppers see none of its replies "
        "until you press Go live. The guide for shop owners shows the next steps:\n\n"
        f"{OWNER_GUIDE_URL}\n",
    )


def refused_email(*, shop: str) -> tuple[str, str]:
    """The refusal email: subject and body (R16, R17, the owner: A)."""
    return (
        f"Your FiveNeurals sign-up for {shop}",
        "Hello,\n\n"
        f"Thank you for signing up {shop} for FiveNeurals. We looked at it, and we can't "
        "start an assistant for this shop, so we have removed it. Nothing was charged.\n",
    )


class SignUp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Validated as an address before anything else, as sign-in's is.
    email: EmailStr
    #: Loose bounds here; ``shop_name`` and ``shop_website`` give the plain words.
    shop_name: str = Field(max_length=500)
    website: str = Field(max_length=1000)


class ConfirmSignUp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)


@router.post("/auth/sign-up", summary="Email a link that signs up a new shop")
async def sign_up(body: SignUp, request: Request, db: DatabaseDep) -> dict[str, object]:
    settings = get_settings()
    # The form's own mistakes first: they reveal nothing, and a typo should not
    # use up the hour's links.
    name = shop_name(body.shop_name)
    website = shop_website(body.website)
    await limit_links(request, str(body.email), refusal=SIGN_UP_LIMITED)

    async with db.identity_session() as session:
        link = await request_sign_up(
            session,
            email=str(body.email),
            name=name,
            website=website,
            console_base_url=settings.console_base_url,
            requested_ip=peer(request),
        )

    result = Mailer(settings).send(
        to=str(body.email), subject=CONFIRM_SUBJECT, body=confirm_body(link.url)
    )
    # The person is told "check your email" regardless, so this line is the
    # only place a delivery failure shows.
    if not result.sent:
        log.error("sign_up_mail_not_delivered", skipped=result.skipped, error=result.error)

    return envelope({"message": SENT_MESSAGE})


@router.post("/auth/confirm-sign-up", summary="Use a sign-up link: the account and a waiting shop")
async def confirm(
    body: ConfirmSignUp, response: Response, request: Request, db: DatabaseDep
) -> dict[str, object]:
    """One transaction, in the new shop's own session: the request is deleted
    (the link works once), the account made when the email has none, the shop
    made waiting for approval, its Owner, and the audit entry.

    **It signs them in, also an existing account** (R15): the link works 15
    minutes and once, as a sign-in link does, so it opens nothing a sign-in
    link would not.
    """
    tenant_id = ids.new_id(ids.TENANT)
    async with db.tenant_session(tenant_id) as session:
        signed = await confirm_sign_up(session, tenant_id=tenant_id, token=body.token)
        if signed is not None:
            await PostgresAuditLog(session).record(
                AuditEntry(
                    tenant_id=tenant_id,
                    event_type=AuditEvent.PEOPLE_CHANGE,
                    actor=signed.user_id,
                    outcome="signed_up",
                    payload={"role": "owner", "new_account": signed.made_account},
                )
            )

    if signed is None:
        log.info("console_sign_up_failed", ip=peer(request))
        return envelope({"signed_in": False, "message": NO_LONGER_VALID})

    set_session_cookie(response, issue(signed.user_id, get_settings().secret_key))
    log.info("console_signed_up", user_id=signed.user_id, tenant_id=tenant_id)
    return envelope({"signed_in": True, "tenant_id": tenant_id, "user_id": signed.user_id})
