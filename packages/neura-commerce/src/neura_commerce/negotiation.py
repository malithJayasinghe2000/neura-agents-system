"""Capability negotiation.

The mechanism that makes "works with any commerce platform" true in practice
rather than on a whiteboard. Without it, the claim collapses the first time a
platform lacks something the agent assumed.

Two jobs:

1. **Compatibility.** Given what an agent needs and what a store offers, decide
   whether they can work together — and say so at *connection* time, not through
   a failed customer conversation weeks later.

2. **Tool filtering.** Compute exactly which tools exist for this store. A tool
   whose requirements are unmet is never registered, so the model is never shown
   it. That is also a security control: **the best defence against tool abuse is
   not registering the tool** (docs/architecture/security-model.md §2.1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from neura_domain import Capability


@dataclass(frozen=True, slots=True)
class Requirement:
    """What some feature needs from a platform."""

    name: str
    required: frozenset[Capability] = field(default_factory=frozenset)
    optional: frozenset[Capability] = field(default_factory=frozenset)

    def is_satisfied_by(self, available: frozenset[Capability]) -> bool:
        return self.required <= available

    def missing_from(self, available: frozenset[Capability]) -> frozenset[Capability]:
        return self.required - available

    def degraded_by(self, available: frozenset[Capability]) -> frozenset[Capability]:
        """Optional capabilities absent — works, but with less."""
        return self.optional - available


@dataclass(frozen=True, slots=True)
class NegotiationResult:
    """The outcome of matching a requirement against a store."""

    requirement: str
    compatible: bool
    missing: frozenset[Capability]
    degraded: frozenset[Capability]

    @property
    def is_fully_supported(self) -> bool:
        return self.compatible and not self.degraded

    def explain(self) -> str:
        """A sentence a merchant can act on.

        Merchants read these when connecting a store, so they name the missing
        capability rather than saying "incompatible".
        """
        if not self.compatible:
            missing = ", ".join(sorted(c.value for c in self.missing))
            return f"{self.requirement} cannot run on this store: it does not support {missing}."
        if self.degraded:
            degraded = ", ".join(sorted(c.value for c in self.degraded))
            return (
                f"{self.requirement} will run with reduced functionality: this store "
                f"does not support {degraded}."
            )
        return f"{self.requirement} is fully supported by this store."


def negotiate(requirement: Requirement, available: frozenset[Capability]) -> NegotiationResult:
    return NegotiationResult(
        requirement=requirement.name,
        compatible=requirement.is_satisfied_by(available),
        missing=requirement.missing_from(available),
        degraded=requirement.degraded_by(available),
    )


def filter_by_capability[ItemT](
    items: list[ItemT],
    available: frozenset[Capability],
    *,
    requires: Callable[[ItemT], frozenset[Capability]],
) -> list[ItemT]:
    """Keep only the items a store can actually support.

    Used to compute the agent's tool set. Generic so the same logic serves tools,
    graph nodes, or anything else gated on platform support.
    """
    return [item for item in items if requires(item) <= available]


def describe_gap(needed: frozenset[Capability], available: frozenset[Capability]) -> str:
    """Human-readable summary of what a store is missing.

    Fed into the system prompt so the model states its limits plainly — "I can't
    cancel orders for this store, let me get a human" — rather than apologising
    vaguely or, worse, claiming to have done something it cannot do.
    """
    missing = needed - available
    if not missing:
        return ""
    return ", ".join(sorted(c.value for c in missing))
