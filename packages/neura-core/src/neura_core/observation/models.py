"""What an observed event *is* — ADR-0044 §4, as a type.

**The model forbids extra fields, and that is the privacy control rather than a
tidiness setting.** §4 names what is stored — an opaque session id, the event
type, the product it refers to, a timestamp — and *"anything the shop did not
send for this purpose"* is not. A shop that also sends an IP address, a user
agent or an email is refused with a 400 that names the field, rather than having
the field quietly dropped: dropped is *"collected and discarded"*, which §3 says
is not a control, and a refusal is how the shop's developer finds out.

**One field is about the product, not the shopper**: ``in_stock`` on a view
(ADR-0049), because *"sold out when it was viewed"* cannot be reconstructed
later.

**An anonymous session id is still personal data** (§4). It is validated for
shape, never for meaning — we cannot tell a keyed hash from a raw session
cookie — so the spec tells the shop to send the former, and the bridge does.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: The scope a key needs to send events. Held **only** by a secret key, and
#: issuable only to a tenant with a data-processing agreement recorded
#: (``ApiKeyRepository.issue``). Named once, here, because the route that
#: demands it and the issuer that guards it must agree on the string.
OBSERVE_WRITE = "observe:write"

#: A shop's clock and ours disagree a little, and a queued delivery arrives a
#: few minutes after the page view it describes. Five minutes is the tolerance
#: the signed-webhook contract already uses for the same reason.
CLOCK_SKEW = timedelta(minutes=5)

#: Opaque tokens only: letters, digits, ``_`` and ``-``. No ``.``, ``@`` or
#: spaces, so an email address or a name cannot pass as an identifier.
_OPAQUE = r"^[A-Za-z0-9_-]+$"


class ObservedEventType(StrEnum):
    """The two things phase 1 records. Owner decision, 2026-09-26.

    **Searches are deliberately absent.** §4 stores a product or category and
    nothing else, and a search points at neither — recording one usefully means
    keeping what a shopper typed, which §4 does not permit. Category and policy
    views are absent because the owner chose these two.
    """

    PRODUCT_VIEWED = "product.viewed"
    """A shopper's browser requested a product page. Needed by ADR-0046 stage 1."""

    CART_ADDED = "cart.added"
    """A product went into a basket — recorded only when the add succeeded."""


class ObservedEvent(BaseModel):
    """One event, exactly as a shop's server sends it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The shop's own id for this event. Its only job is making a retried
    #: delivery idempotent: the bridge delivers at least once, and a page view
    #: counted twice because a response was slow is a number that is wrong.
    event_id: str = Field(min_length=16, max_length=64, pattern=_OPAQUE)
    #: Opaque, and derived by the shop — never its session cookie itself, which
    #: would hand anyone who read this table a way into a shopper's session.
    session_id: str = Field(min_length=16, max_length=128, pattern=_OPAQUE)
    type: ObservedEventType
    #: The merchant's own product id, as the nine endpoints report it.
    product_id: str = Field(min_length=1, max_length=128, pattern=_OPAQUE)
    occurred_at: datetime
    #: Could the product be bought at the moment of the view? ADR-0049: the
    #: canonical model's word, meaning *at least one variant is in stock*.
    #: Required on a view — the sold-out count cannot use one without it — and
    #: refused on a basket add, where it could only be contradictory.
    in_stock: bool | None = None

    @model_validator(mode="after")
    def _stock_belongs_to_a_view(self) -> ObservedEvent:
        if self.type is ObservedEventType.PRODUCT_VIEWED and self.in_stock is None:
            raise ValueError("a product.viewed event must say whether it was in_stock (ADR-0049)")
        if self.type is ObservedEventType.CART_ADDED and self.in_stock is not None:
            raise ValueError(
                "in_stock is not sent on cart.added — an add is in stock by definition"
            )
        return self

    @field_validator("occurred_at")
    @classmethod
    def _must_be_aware(cls, value: datetime) -> datetime:
        """A naive time is an instant nobody can place — AGENTS.md's UTC rule."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must carry a timezone offset")
        return value


def inadmissible(event: ObservedEvent, *, now: datetime, retention: timedelta) -> str | None:
    """Why this event may not be stored, or ``None`` if it may.

    **Too old** is refused because it would be deleted by the next sweep anyway,
    and storing it until then is holding data with no purpose. **In the future**
    is refused because retention is measured from ``occurred_at``: a shop that
    sends next year's date would otherwise keep a row for a year.
    """
    if event.occurred_at > now + CLOCK_SKEW:
        return "occurred_at is in the future"
    if event.occurred_at < now - retention:
        return "occurred_at is older than the retention period"
    return None


__all__ = [
    "CLOCK_SKEW",
    "OBSERVE_WRITE",
    "ObservedEvent",
    "ObservedEventType",
    "inadmissible",
]
