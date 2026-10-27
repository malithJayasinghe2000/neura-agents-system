"""Answering a handed-over shopper from the dashboard. ADR-0062 §6 to §8.

    GET  /v1/console/shops/{tenant_id}/conversations/{id}/waiting    the address, and the email to send
    POST /v1/console/shops/{tenant_id}/conversations/{id}/answered   Mark as answered

**NEURA sends nothing.** The team member presses *Answer by email* and their own
email app opens, filled with what ``…/waiting`` gives; they send it from the
shop's email (R27). These two routes are the whole of the dashboard's part:
show the address to whoever may answer, and forget it once they have.

**Behind ``shop:handovers:write``**, Owner and Support (§8). A screen the console
serves for every assistant, so the permission names no agent (G102, G88).
Conversations itself shows only *that* someone waits, never the address.

**Where the address comes from:**

* typed by the shopper after the handover: ``waiting_answers.email``;
* a signed-in customer: **read from the shop, now, and never stored** (§2, §6),
  through the shop's own bridge (``get_customer``, the optional
  ``customer.read``). When the shop cannot give it (no such customer, the bridge
  does not list ``customer.read``, or it did not answer), the screen shows the
  customer's id, to find in the shop's own admin.

**Mark as answered** deletes the address at once (R30), records who and when,
and writes an audit entry naming who, never the address (§7). It cannot be
undone; the dashboard asks first.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_agent_core.conversations import ConversationRepository, Role
from neura_agent_core.waiting import WaitingAnswerRepository, WaitingReach
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_api.routes.console_people import who_made
from neura_core import ConflictError, NotFoundError, get_logger
from neura_core.identity.roles import HANDOVERS_WRITE
from neura_core.tenancy import TenantRepository, answer_email
from neura_domain import Capability

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])


class NotWaitingError(ConflictError):
    """The chat is not waiting for the shop's answer: nobody left a way to reach
    them, or someone has already marked it answered."""

    code = "NOT_WAITING"


@router.get(
    "/conversations/{conversation_id}/waiting",
    summary="A waiting shopper's address, and the email the team member sends",
)
async def read_waiting(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(HANDOVERS_WRITE))],
    conversation_id: str,
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        conversations = ConversationRepository(session)
        conversation = await conversations.get(actor.tenant_id, conversation_id)
        if conversation is None:
            raise NotFoundError("No such conversation.", details={"id": conversation_id})
        wait = await WaitingAnswerRepository(session).get(actor.tenant_id, conversation_id)
        if wait is None or not wait.waiting:
            raise NotWaitingError("This chat is not waiting for an answer.")
        tenant = await TenantRepository(session).get(actor.tenant_id)
        messages = await conversations.messages(actor.tenant_id, conversation_id, limit=1)

    # The first thing the shopper asked, as stored (tokens and all, as
    # Conversations shows it): the question the email answers.
    question = next((m.content for m in messages if m.role is Role.SHOPPER), None)
    subject, body = answer_email((tenant.name if tenant else "") or "our shop", question)

    customer_id: str | None = None
    if wait.reach is WaitingReach.EMAIL:
        email = wait.email
    else:
        customer_id = conversation.customer_external_id
        email = await _customers_email(request, actor.tenant_id, customer_id)

    return envelope(
        {
            "reach": wait.reach.value,
            "since": wait.created_at.isoformat(),
            "email": email,
            # Only when the shop could not give a signed-in customer's address:
            # who to look up in the shop's own admin.
            "customer_id": customer_id if email is None else None,
            "subject": subject,
            "body": body,
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.post(
    "/conversations/{conversation_id}/answered",
    summary="Mark a waiting shopper as answered: their email is deleted",
)
async def mark_answered(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(HANDOVERS_WRITE))],
    conversation_id: str,
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        if await ConversationRepository(session).get(actor.tenant_id, conversation_id) is None:
            raise NotFoundError("No such conversation.", details={"id": conversation_id})
        waiting = WaitingAnswerRepository(session)
        if not await waiting.mark_answered(
            actor.tenant_id, conversation_id, answered_by=actor.user_id
        ):
            raise NotWaitingError("This chat is not waiting for an answer.")
        await PostgresAuditLog(session).record(
            AuditEntry(
                tenant_id=actor.tenant_id,
                event_type=AuditEvent.ESCALATION,
                actor=actor.user_id,
                outcome="handover.answered",
                conversation_id=conversation_id,
                # Who, and the chat. Never the address (ADR-0062 §7).
                payload={},
            )
        )
        answered = await waiting.get(actor.tenant_id, conversation_id)
        by = await who_made(session, actor.tenant_id, actor.user_id)

    log.info(
        "handover_answered",
        tenant_id=actor.tenant_id,
        conversation_id=conversation_id,
        user_id=actor.user_id,
    )
    return envelope(
        {
            "answered_at": answered.answered_at.isoformat()
            if answered and answered.answered_at
            else None,
            "answered_by": by,
        },
        request_id=getattr(request.state, "request_id", None),
    )


async def _customers_email(request: Request, tenant_id: str, customer_id: str | None) -> str | None:
    """A signed-in customer's address, from the shop, now. ``None`` when the shop
    cannot give it: the screen then names the customer instead. Never stored."""
    if not customer_id:
        return None
    try:
        store = await request.app.state.stores.connect(tenant_id)
    except Exception as exc:  # the shop is not connected, or its bridge cannot be built
        log.info("handover_customer_unreachable", tenant_id=tenant_id, reason=type(exc).__name__)
        return None
    try:
        if Capability.CUSTOMER_READ not in store.capabilities:
            return None
        customer = await store.adapter.get_customer(customer_id)
        return customer.email if customer is not None and customer.email else None
    except Exception as exc:  # the shop did not answer: the id is shown instead
        log.info("handover_customer_unreachable", tenant_id=tenant_id, reason=type(exc).__name__)
        return None
    finally:
        close = getattr(store.adapter, "aclose", None)
        if close is not None:
            await close()


__all__ = ["NotWaitingError", "router"]
