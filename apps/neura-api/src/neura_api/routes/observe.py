"""``POST /v1/observe/events`` — a shop's server tells us a shopper did something.

[ADR-0044](../../../../../docs/architecture/adr/0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)
phase 1: **collect, prove the pipe.** There is no ``GET`` here, and nothing is
shown to a shopper; the one screen that reads these rows is the merchant's
sold-out count, ``console_sold_out`` (ADR-0046 stage 1).

**The switch is not in this file.** It lives in the shop and governs *sending*
(§3): a shop that has not turned observation on never calls this, so there is
nothing for us to discard. Everything below is what we refuse *in addition*,
and each refusal is code (AGENTS.md rule 3):

1. **A secret key with ``observe:write``.** A browser key is refused even if it
   somehow holds the scope — *"no script of ours runs in a shopper's
   browser"* (§2), and an ``fn_pk_`` key is by definition a browser's.
2. **A data-processing agreement on record** (ADR-0042 §2). Refused at key
   issue too; checked again here because an agreement can be withdrawn after.
3. **Only §4's fields.** Anything else in the body — an IP, a user agent, an
   email — is a 400 naming the field, not a silent drop.
4. **A timestamp inside the retention window**, so the shop's clock cannot
   decide how long a row lives.

**Nothing in this module logs a session id.** Not the request, not a refusal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from neura_api.dependencies import require
from neura_api.envelopes import envelope
from neura_api.jobs.retention import enqueue_sweep
from neura_core import ForbiddenError, ValidationError, get_settings
from neura_core.observation import (
    OBSERVE_WRITE,
    ObservedEvent,
    ObservedEventRepository,
    inadmissible,
)
from neura_core.tenancy import ApiKeyKind, AuthenticatedCaller

router = APIRouter(prefix="/observe", tags=["observe"])


def admit(caller: AuthenticatedCaller) -> None:
    """The two refusals that are about *who*, not *what*. Pure, so it is testable
    without a database — and so the route cannot reorder them past the write."""
    if caller.api_key.kind is not ApiKeyKind.SECRET:
        raise ForbiddenError(
            "Events come from the shop's server, never from a browser. Use a secret key.",
            code="OBSERVE_BROWSER_KEY",
        )
    if not caller.tenant.may_hold_personal_data:
        raise ForbiddenError(
            "No data-processing agreement is on record for this shop, so nothing "
            "about its shoppers may be stored.",
            code="DPA_REQUIRED",
        )


@router.post(
    "/events",
    summary="Record one thing a shopper did — sent by the shop's server",
    status_code=202,
    responses={
        202: {"description": "Stored, or already stored under this event_id."},
        400: {"description": "A field §4 does not permit, or a timestamp outside the window"},
        403: {"description": "A browser key, or no data-processing agreement on record"},
    },
)
async def record_event(
    request: Request,
    event: ObservedEvent,
    caller: Annotated[AuthenticatedCaller, Depends(require(OBSERVE_WRITE))],
) -> dict[str, Any]:
    admit(caller)

    settings = get_settings()
    now = datetime.now(UTC)
    reason = inadmissible(
        event, now=now, retention=timedelta(days=settings.retention_observed_events_days)
    )
    if reason is not None:
        raise ValidationError(reason, code="OBSERVED_EVENT_OUT_OF_WINDOW")

    async with request.app.state.database.tenant_session(caller.tenant_id) as session:
        stored = await ObservedEventRepository(session).record(caller.tenant_id, event)
        # The row and the deletion that will remove it commit together.
        await enqueue_sweep(session, caller.tenant_id, now=now)

    return envelope(
        {"event_id": event.event_id, "stored": stored},
        request_id=getattr(request.state, "request_id", None),
    )


__all__ = ["admit", "router"]
