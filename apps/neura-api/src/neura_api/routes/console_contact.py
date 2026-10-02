"""The shop's contact details, named in every handover. ADR-0055, `console.md §3.4`.

    GET /v1/console/shops/{tenant_id}/contact    {"email": …, "phone": …}
    PUT /v1/console/shops/{tenant_id}/contact    {"email": "…", "phone": "…"}

Typed once by the owner on Shop connection. A handed-over shopper reads *"I can't
help with this here. Please contact our store:"* and these (`neura_core.tenancy.
handover_message`, put on by the turn service).

Behind the console session, the shop taken from the membership (`acting_for`).
**Only the two keys change** in the shop's settings, merged like the mode
(ADR-0054 §5). Both are optional; an empty field clears one. A wrong value is
refused with a 400 naming the field, before anything is written. Every change
writes an audit entry naming **which** fields changed, never their values; a
save that changes nothing records nothing.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.dependencies import acting_for
from neura_api.envelopes import envelope
from neura_core import get_logger
from neura_core.tenancy import TenantConfig, TenantRepository, handover_message

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: Looks like an address: something, one ``@``, a domain with a dot. Whether it
#: receives mail is the owner's to know; this only stops a typing slip.
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$")

#: Digits with the usual separators, an optional leading ``+``.
PHONE = re.compile(r"^\+?[0-9][0-9 ()\-]*$")

#: E.164's limit is 15 digits; fewer than 6 is not a number a shopper can call.
PHONE_DIGITS = range(6, 16)


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if not EMAIL.match(value):
            raise ValueError(
                "this doesn't look like an email address, for example hello@yourshop.com"
            )
        return value

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        digits = sum(ch.isdigit() for ch in value)
        if not PHONE.match(value) or digits not in PHONE_DIGITS:
            raise ValueError(
                "use digits, spaces, + - and brackets only, for example +94 11 234 5678"
            )
        return value


def _shown(config: TenantConfig) -> dict[str, str | None]:
    return {"email": config.contact_email, "phone": config.contact_phone}


def _answer(config: TenantConfig) -> dict[str, str | None]:
    """The details, and the sentence a handed-over shopper reads with them, made
    here so the dashboard shows the server's words and never a copy of them."""
    return {**_shown(config), "handover": handover_message(config)}


@router.get("/contact", summary="The shop's contact details, named in every handover")
async def read_contact(request: Request, tenant_id: str) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        tenant = await TenantRepository(session).require(actor.tenant_id)
    return envelope(_answer(tenant.config), request_id=getattr(request.state, "request_id", None))


@router.put("/contact", summary="Save the shop's contact details")
async def save_contact(request: Request, tenant_id: str, body: ContactRequest) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)

    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        tenants = TenantRepository(session)
        before = _shown((await tenants.require(actor.tenant_id)).config)
        after = {"email": body.email, "phone": body.phone}
        changed = [field for field in ("email", "phone") if before[field] != after[field]]
        if changed:
            await tenants.set_contact(actor.tenant_id, email=body.email, phone=body.phone)
            await PostgresAuditLog(session).record(
                AuditEntry(
                    tenant_id=actor.tenant_id,
                    event_type=AuditEvent.CONFIG_CHANGE,
                    actor=actor.user_id,
                    outcome="contact.changed",
                    # Which fields, never their values.
                    payload={"fields": changed},
                )
            )

    log.info(
        "console_contact_saved", tenant_id=actor.tenant_id, user_id=actor.user_id, changed=changed
    )
    saved = TenantConfig(contact_email=body.email, contact_phone=body.phone)
    return envelope(_answer(saved), request_id=getattr(request.state, "request_id", None))
