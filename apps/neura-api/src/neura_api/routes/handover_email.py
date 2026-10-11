"""``POST /v1/conversations/{id}/email`` — a handed-over shopper leaves an address. ADR-0062.

What the chat box sends when a shopper presses **Send** in the email box under a
handover (``ask_email`` on the reply). The shop's team then answers by email,
**from the shop's own email app**: NEURA sends nothing to a shopper (CLAUDE.md
§2, unchanged), and this route stores an address and returns one sentence.

**Mounted once and naming no agent**, as the dispatched chat is: the agent is
read from the conversation, as data, and the key must hold that agent's
``<agent>:chat:write``, the scope the chat box already sends messages with, so no
shop makes a new key (§10).

**The address is never a chat message** (§10). It never reaches the guard, the
model, a trace or ``conversation_messages``; it goes to ``waiting_answers`` and
nowhere else. Nor is it ever repeated: not in a log line, and **not in an error
answer**, which is why it is a plain string here and checked by
:func:`shopper_email` rather than by the request model (FastAPI's own validation
error repeats what was sent).

Refused, each with its own code so the chat box can say the right thing:

* ``INVALID_EMAIL`` (400): it does not look like an address;
* ``NOT_FOUND`` (404): no such chat for this key's shop (another shop's is the
  same answer, under its row-level security);
* ``NOT_HANDED_OVER`` (409): this chat was never handed over to the shop
  (practice mode included: a held handover reached nobody);
* ``ALREADY_WAITING`` (409): it already waits, on an address left earlier or on
  a signed-in customer's record. The first address stands.
"""

from __future__ import annotations

from typing import Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from neura_agent_core.conversations import ConversationRepository
from neura_agent_core.waiting import MAX_EMAIL_CHARS, WaitingAnswerRepository
from neura_api.dependencies import authenticate_request
from neura_api.envelopes import envelope
from neura_api.jobs.retention import enqueue_sweep
from neura_api.ratelimit import enforce
from neura_api.routes.agent import _rate_limit
from neura_core import ConflictError, NotFoundError, ValidationError, get_logger
from neura_core.tenancy import WRONG_EMAIL, email_thanks, require_scopes

log = get_logger(__name__)

router = APIRouter(tags=["handover"])


class LeaveEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Checked by :func:`shopper_email`, not here: a constraint on the model would
    #: make a refusal repeat the address.
    email: str


def shopper_email(typed: str) -> str | None:
    """The address as it will be kept, or ``None`` when it does not look like one.

    Trimmed; the domain written the standard way, the part before ``@`` as typed.
    No look-up of the domain: whether it receives mail is the shop's to find out
    when it answers, and a check here would be a network call per shopper.
    """
    text = typed.strip()
    if not text or len(text) > MAX_EMAIL_CHARS or any(char.isspace() for char in text):
        return None
    try:
        return validate_email(text, check_deliverability=False).normalized
    except EmailNotValidError:
        return None


@router.post(
    "/conversations/{conversation_id}/email",
    summary="A handed-over shopper leaves an email so the shop can answer",
    responses={
        400: {"description": "Not an email address (INVALID_EMAIL)"},
        404: {"description": "No such conversation for this key's shop"},
        409: {
            "description": "Never handed over, or already waiting (NOT_HANDED_OVER, ALREADY_WAITING)"
        },
        429: {"description": "Rate limited"},
    },
)
async def leave_email(
    request: Request, conversation_id: str, body: LeaveEmail, response: Response
) -> dict[str, Any]:
    caller = await authenticate_request(request)
    # The chat's own limits: an address is one more message in it.
    verdict = await _rate_limit(request, caller, conversation_id)
    response.headers.update(verdict.headers())
    enforce(verdict)

    email = shopper_email(body.email)
    if email is None:
        raise ValidationError(WRONG_EMAIL, code="INVALID_EMAIL")

    async with request.app.state.database.tenant_session(caller.tenant_id) as session:
        conversation = await ConversationRepository(session).get(caller.tenant_id, conversation_id)
        if conversation is None:
            # Another shop's chat looks the same as none: under RLS it is not there.
            raise NotFoundError("No such conversation.", details={"id": conversation_id})
        require_scopes(caller, f"{conversation.agent_key}:chat:write")
        # `escalations` counts live handovers only: a held one (practice mode)
        # is `shadowed` and reached nobody (ADR-0062 §9).
        if conversation.escalations == 0:
            raise ConflictError(
                "This conversation was not handed over to the shop.", code="NOT_HANDED_OVER"
            )
        if not await WaitingAnswerRepository(session).leave_email(
            caller.tenant_id, conversation_id, email
        ):
            raise ConflictError(
                "This conversation is already waiting for the shop's answer.",
                code="ALREADY_WAITING",
            )
        # Something to expire books the sweep that will, in this transaction
        # (ADR-0042 §3). A no-op when one is already live, as it will be.
        await enqueue_sweep(session, caller.tenant_id)

    # Never the address (ADR-0062 §10).
    log.info("handover_email_left", tenant_id=caller.tenant_id, conversation_id=conversation_id)
    return envelope(
        {"reply": email_thanks(email)}, request_id=getattr(request.state, "request_id", None)
    )


__all__ = ["MAX_EMAIL_CHARS", "LeaveEmail", "router", "shopper_email"]
