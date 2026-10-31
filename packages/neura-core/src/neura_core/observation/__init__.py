"""Observed events — ADR-0044 phase 1: collect, prove the pipe, show nothing.

**A shopper may be observed only for a shop that switches it on, and only from
that shop's own server.** The switch is not here. It lives in the shop's
configuration and governs *sending* (§3), so a shop that has not switched it on
sends nothing and this package receives nothing — the data never exists, rather
than arriving and being discarded.

What this package does enforce, in code rather than in a prompt:

* the fields — :class:`ObservedEvent` forbids anything §4 does not name;
* who may send — :data:`OBSERVE_WRITE`, on a secret key only, and only for a
  tenant with a data-processing agreement recorded (ADR-0042 §2);
* how long it lives — the retention sweep in ``neura_api.jobs.retention``.

**Nothing is scored, and nothing is shown to a shopper.** Phase 2 is the
points table. What is shown is merchant-facing and counts only, never a
session: ADR-0046 stage 1's views of sold-out products, and ADR-0071's in-stock
products many visitors opened and few added to the cart.
"""

from neura_core.observation.models import (
    CLOCK_SKEW,
    OBSERVE_WRITE,
    ObservedEvent,
    ObservedEventType,
    inadmissible,
)
from neura_core.observation.repository import (
    RARELY_MIN_VISITORS,
    RARELY_ONE_IN,
    ObservedEventRepository,
    RarelyAdded,
    SoldOutDemand,
)
from neura_core.observation.schema import OBSERVED_EVENTS, observed_events

__all__ = [
    "CLOCK_SKEW",
    "OBSERVED_EVENTS",
    "OBSERVE_WRITE",
    "RARELY_MIN_VISITORS",
    "RARELY_ONE_IN",
    "ObservedEvent",
    "ObservedEventRepository",
    "ObservedEventType",
    "RarelyAdded",
    "SoldOutDemand",
    "inadmissible",
    "observed_events",
]
