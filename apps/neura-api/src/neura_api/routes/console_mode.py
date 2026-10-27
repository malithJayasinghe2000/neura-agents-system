"""Practice mode, switched by the shop owner. ADR-0054, `console.md §3.1` (Home).

    PUT /v1/console/shops/{tenant_id}/mode    {"mode": "live" | "shadow"}

*Go live* and *Back to practice mode* on Home. Behind the console session, the
shop taken from the membership (`acting_for`), never from the request.

**Only the mode changes** (§5): one key merged into the shop's settings, so a
per-intent practice list and any key a newer deployment wrote are kept. Every
change writes an audit entry in the same transaction, naming who and the mode
before and after; pressing for the mode the shop is already in changes nothing
and records nothing.

A shopper already chatting meets the new mode on their next reply: the turn
reads the mode when the reply is released (§6, G72, `turns.py`).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_core import get_logger
from neura_core.identity.roles import MODE_WRITE
from neura_core.tenancy import TenantRepository, TurnMode

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: What the audit log calls each direction: the merchant's words for the two
#: modes the dashboard can set.
OUTCOME = {TurnMode.LIVE: "mode.live", TurnMode.SHADOW: "mode.practice"}


class ModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The code's own words: ``live``, or ``shadow`` (practice mode).
    mode: TurnMode


@router.put("/mode", summary="Go live, or back to practice mode")
async def set_mode(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(MODE_WRITE))],
    body: ModeRequest,
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        tenants = TenantRepository(session)
        before = (await tenants.require(actor.tenant_id)).config.mode
        changed = before is not body.mode
        if changed:
            await tenants.set_mode(actor.tenant_id, body.mode)
            await PostgresAuditLog(session).record(
                AuditEntry(
                    tenant_id=actor.tenant_id,
                    event_type=AuditEvent.CONFIG_CHANGE,
                    actor=actor.user_id,
                    outcome=OUTCOME[body.mode],
                    payload={"from": before.value, "to": body.mode.value},
                )
            )

    log.info(
        "console_mode_set",
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        mode=body.mode.value,
        changed=changed,
    )
    return envelope(
        {"mode": body.mode.value, "withheld": body.mode is TurnMode.SHADOW, "changed": changed},
        request_id=getattr(request.state, "request_id", None),
    )
