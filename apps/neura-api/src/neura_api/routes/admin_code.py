"""The code from a FiveNeurals admin's phone. ADR-0067.

Three routes, **the only admin routes that open before the code is typed**
(``AdminOnly(code=False)``): they still need a live admin signed in within 12
hours (ADR-0061 §4).

* ``POST /admin/code/setup``: a new key, its QR code and the address an
  authenticator app reads. **Refused once setup is finished**, so the key is
  never shown twice.
* ``POST /admin/code/setup/confirm``: the first code, which finishes setup.
* ``POST /admin/code``: the code at a sign-in.

A correct code issues the sign-in cookie again **with the same sign-in time**
and the time of the code, so the 12 hours still count from the email link and a
new email sign-in asks again (R56). A wrong code is **400 ``WRONG_CODE``**; the
5th wrong code in a row, and any code for 15 minutes after, **429
``TOO_MANY_CODES``**.
"""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from typing import Annotated

import segno
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from neura_api.dependencies import AdminActor, AdminOnly, DatabaseDep
from neura_api.envelopes import envelope
from neura_api.routes.console import set_session_cookie
from neura_core import ConflictError, RateLimitError, ValidationError, get_logger, get_settings
from neura_core.identity import issue
from neura_core.identity.admin_codes import (
    CodeResult,
    SetupFinishedError,
    check_code,
    confirm_setup,
    start_setup,
)
from neura_core.identity.schema import users
from neura_core.identity.totp import grouped, otpauth_uri

log = get_logger(__name__)

router = APIRouter(prefix="/admin/code", tags=["admin"])

SignedInAdmin = Annotated[AdminActor, Depends(AdminOnly(code=False))]

WRONG_CODE = "WRONG_CODE"
TOO_MANY_CODES = "TOO_MANY_CODES"


class Code(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=12)


@router.post("/setup", summary="A new key for the code from the admin's phone")
async def setup(actor: SignedInAdmin, db: DatabaseDep) -> dict[str, object]:
    async with db.identity_session(actor.user_id) as session:
        email = await session.scalar(select(users.c.email).where(users.c.id == actor.user_id))
        try:
            secret = await start_setup(session, actor.user_id, kek=get_settings().kek)
        except SetupFinishedError:
            raise ConflictError("Your code is already set up.", code="ADMIN_CODE_SET_UP") from None
    uri = otpauth_uri(secret, account=str(email or actor.user_id))
    return envelope({"key": grouped(secret), "uri": uri, "qr_svg": _qr(uri)})


@router.post("/setup/confirm", summary="The first code, which finishes setup")
async def confirm(
    body: Code, actor: SignedInAdmin, response: Response, db: DatabaseDep
) -> dict[str, object]:
    async with db.identity_session(actor.user_id) as session:
        result = await confirm_setup(session, actor.user_id, body.code, kek=get_settings().kek)
    return _answer(result, actor, response)


@router.post("", summary="The code at an admin sign-in")
async def code(
    body: Code, actor: SignedInAdmin, response: Response, db: DatabaseDep
) -> dict[str, object]:
    async with db.identity_session(actor.user_id) as session:
        result = await check_code(session, actor.user_id, body.code, kek=get_settings().kek)
    return _answer(result, actor, response)


def _answer(result: CodeResult, actor: AdminActor, response: Response) -> dict[str, object]:
    if result is CodeResult.STOPPED:
        raise RateLimitError(
            "Too many wrong codes. Wait 15 minutes, then try again.", code=TOO_MANY_CODES
        )
    if result is CodeResult.NOT_READY:
        raise ConflictError("Set up the code from your phone first.", code="ADMIN_CODE_SETUP")
    if result is CodeResult.WRONG:
        raise ValidationError(
            "That code didn't work. Check that the time on your phone is right, and type "
            "the newest code.",
            code=WRONG_CODE,
        )
    set_session_cookie(
        response,
        issue(
            actor.user_id,
            get_settings().secret_key,
            now=actor.signed_in_at,
            code_at=datetime.now(UTC),
        ),
    )
    log.info("admin_code_typed", user_id=actor.user_id)
    return envelope({"ok": True})


def _qr(uri: str) -> str:
    """The QR code as an SVG, for an ``<img>``: it carries the key, so it is made
    here and never stored."""
    out = io.BytesIO()
    segno.make(uri, error="m").save(out, kind="svg", scale=6, border=2, dark="#0a0a0a")
    return "data:image/svg+xml;base64," + base64.b64encode(out.getvalue()).decode()


__all__ = ["router"]
