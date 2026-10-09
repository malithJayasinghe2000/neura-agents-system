"""The customer sign-in secret. ADR-0057 §3, `console.md §3.4`.

    GET  /v1/console/shops/{tenant_id}/customer-secret    {"made_at": … | null}
    POST /v1/console/shops/{tenant_id}/customer-secret    {"secret": "fn_cs_…", "made_at": …}

The shop's server signs a **customer pass** with this secret for each signed-in
shopper, and the chat box carries it, so *"where is my order?"* can be answered
for that shopper and nobody else. The owner makes it once on Shop connection and
gives it to their developer; *make a new one* replaces it, and passes signed with
the old one stop working at once (NEURA checks them, unlike the shop token).

Behind the console session, the shop taken from the membership (`acting_for`).
**The secret is shown by the response that made it and by nothing else**: the
read gives only when it was made. Each make writes an audit entry naming who,
never the secret, in the same transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.dependencies import acting_for
from neura_api.envelopes import envelope
from neura_core import get_logger
from neura_core.tenancy import CustomerSecretRepository

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])


@router.get("/customer-secret", summary="When the customer sign-in secret was made")
async def read_secret(request: Request, tenant_id: str) -> dict[str, Any]:
    """Only when it was made, or ``null``. Never the secret."""
    actor = await acting_for(request, tenant_id)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        made_at = await CustomerSecretRepository(session).made_at(actor.tenant_id)
    return envelope(
        {"made_at": _iso(made_at)}, request_id=getattr(request.state, "request_id", None)
    )


@router.post("/customer-secret", summary="Make the customer sign-in secret, or a new one")
async def make_secret(request: Request, tenant_id: str) -> dict[str, Any]:
    """Returned **once**. Making another replaces it at once (ADR-0057 §3)."""
    actor = await acting_for(request, tenant_id)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        secrets = CustomerSecretRepository(session)
        replacing = await secrets.made_at(actor.tenant_id) is not None
        secret = await secrets.make(actor.tenant_id, made_by=actor.user_id)
        made_at = await secrets.made_at(actor.tenant_id)
        await PostgresAuditLog(session).record(
            AuditEntry(
                tenant_id=actor.tenant_id,
                event_type=AuditEvent.CONFIG_CHANGE,
                actor=actor.user_id,
                outcome="customer_secret.replaced" if replacing else "customer_secret.made",
                payload={},
            )
        )

    log.info(
        "console_customer_secret_made",
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        replaced=replacing,
    )
    return envelope(
        {"secret": secret, "made_at": _iso(made_at)},
        request_id=getattr(request.state, "request_id", None),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
