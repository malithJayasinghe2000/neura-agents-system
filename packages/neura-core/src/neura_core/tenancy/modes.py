"""How much rope a tenant gives the agent, per intent.

[agent-runtime.md §6](../../../../../docs/architecture/agent-runtime.md) specifies
shadow mode as a *progression*, and the load-bearing sentence is the one about
granularity: mode is per-tenant **and** per-intent, because that is how a merchant
is talked into adopting this at all. They run order status live while returns
policy is still being watched.

## Two modes exist here, and §6 names four

``LIVE`` and ``SHADOW`` are implemented. ``SUGGEST`` and ``SUPERVISED`` are
**deliberately absent rather than accepted and ignored**:

* ``SUGGEST`` — "nothing to the customer, the human sees a draft" — is
  byte-for-byte ``SHADOW`` from this layer's point of view. What separates them is
  a console for the human to read the draft in, and that is Phase 2
  ([roadmap](../../../../../docs/roadmap.md)). Adding the value now would mean two
  names for one behaviour, and the day the console arrives somebody has to work
  out which tenants meant which.
* ``SUPERVISED`` — "the agent replies, a human can recall it within N seconds" —
  needs a recall path, a timer and somewhere for the human to press the button.
  None of that exists.

``TenantConfig``'s own docstring is the rule being followed: *a knob nothing
consults is a setting that appears to work*.

**An unrecognised mode resolves to ``SHADOW``, and that direction is the whole
point.** Two rules meet here and they pull against each other: ``TenantConfig``
ignores unknown keys on purpose, so that a config written by a newer deployment
does not stop a rolled-back one from reading its own tenants — and a mode is
exactly the field where silently falling back to the default would be *more*
permissive than the merchant asked for. A tenant who wrote ``supervised``, on a
deployment that has never heard of it, must not get ``LIVE``. Refusing to load the
tenant would honour that and break the rollback rule; resolving to ``SHADOW``
honours both, because the failure shows up as an agent that has gone quiet rather
than as one that has started talking. Loudly logged, never silent.

## What SHADOW does and does not change

It changes **one** thing: the shopper does not receive the reply. Everything else
about the turn runs exactly as it would live — the same graph, the same tools, the
same policy engine, the same ``verify`` — because a shadow run whose behaviour
differs from the live one measures a system nobody is going to ship.

Two consequences follow and both are deliberate:

* **A shadow turn still costs money and still writes a usage row.** The merchant
  is paying for the evidence, and hiding that in the billing would be a surprise
  on the invoice rather than a kindness.
* **A shadow turn is not written into the transcript as an agent message.** The
  shopper never read it, so a later turn must not "remember" saying it. It goes to
  ``shadow_turns`` instead, which is the queue a human grades.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from neura_core.logging import get_logger

log = get_logger(__name__)


class TurnMode(StrEnum):
    """What happens to the reply once the graph has produced it."""

    LIVE = "live"
    """The shopper reads it. The behaviour of every turn before this module existed."""

    SHADOW = "shadow"
    """The shopper reads nothing. The turn is recorded for a human to grade.

    Not a dry run — the tools really ran and the models really cost money. The
    only difference is who sees the answer.
    """


def coerce_mode(value: Any) -> TurnMode:
    """Read a stored mode, resolving anything unrecognised to ``SHADOW``.

    Called by ``TenantConfig``'s validator rather than by application code. See
    the module docstring for why the fallback withholds instead of defaulting:
    the two mistakes are not symmetric, and only one of them puts words in front
    of a shopper the merchant did not agree to.
    """
    if isinstance(value, TurnMode):
        return value
    try:
        return TurnMode(value)
    except ValueError:
        log.error("unknown_turn_mode", value=str(value), resolved_to=TurnMode.SHADOW.value)
        return TurnMode.SHADOW


def resolve_turn_mode(
    *,
    tenant_mode: TurnMode,
    shadow_intents: frozenset[str],
    intent: str | None,
) -> TurnMode:
    """The mode this turn ends in, given the tenant's setting and the intent.

    **Shadow wins ties, in both directions.** A tenant in ``SHADOW`` stays in
    shadow whatever the intent, and a tenant in ``LIVE`` still shadows the intents
    it has named. There is deliberately no way to spell "live for this intent even
    though the tenant is in shadow": the risky direction of a mistake here is a
    shopper reading something a merchant thought nobody would read, and a rule
    that can only ever *withhold* cannot make that mistake.

    ``intent`` is ``None`` on a turn that never reached the router — a blocked
    attack, a provider outage. Those follow the tenant's own mode, because there
    is no intent to consult and falling back to ``LIVE`` would answer a shopper
    the merchant had not agreed to answer.
    """
    if tenant_mode is TurnMode.SHADOW:
        return TurnMode.SHADOW
    if intent is not None and intent in shadow_intents:
        return TurnMode.SHADOW
    return TurnMode.LIVE


__all__ = ["TurnMode", "coerce_mode", "resolve_turn_mode"]
