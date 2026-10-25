"""NEURA-GROW's identity card.

Same shape as CARE's and SELL's (docs/architecture/tenancy-and-packaging.md
§2.2), with one field they do not need: **``chat``**. GROW's first surface is a
nightly job and a dashboard page (ADR-0064); no shopper ever talks to it. So it
declares no ``handles`` for the dispatcher, no shopper scopes for a key, and
``chat = False``, which the API reads to mount no chat for it and the dispatcher
reads to leave it out of the agents a shopper's message can reach.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from neura_domain import Capability


class AgentManifest(BaseModel):
    """Declared metadata for one sellable agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    version: str
    description: str
    requires_capabilities: frozenset[Capability]
    optional_capabilities: frozenset[Capability] = frozenset()
    scopes: frozenset[str] = frozenset()
    route_prefix: str
    #: Whether shoppers talk to this agent. False: no chat routes are mounted
    #: and the dispatcher never chooses it. An agent with a chat leaves this out.
    chat: bool = True
    #: A job kind the API books once a day for a shop with this agent, from the
    #: shop's first chat (``neura_api.jobs.daily``). An agent without one leaves
    #: this out.
    daily_job: str | None = None


MANIFEST = AgentManifest(
    key="grow",
    name="NEURA-GROW",
    version="0.1.0",
    description=(
        "The marketing agent. First surface: Missing from your pages, the "
        "questions shoppers asked that the shop's own pages do not answer, "
        "found once a night in the shop's chats. Read-only; writes nothing to "
        "the shop and sends nothing to anyone."
    ),
    # None: GROW reads NEURA's own record of the shop's chats and synced
    # catalogue, and never calls the shop.
    requires_capabilities=frozenset(),
    route_prefix="/v1/grow",
    chat=False,
    # The night check (neura_agent_grow.jobs): it reads the shop's chats.
    daily_job="grow.gaps.scan",
)

__all__ = ["MANIFEST", "AgentManifest"]
