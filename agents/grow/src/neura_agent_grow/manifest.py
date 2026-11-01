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

from neura_agent_core.calendar import CALENDAR_PLANS
from neura_agent_core.gaps import PAGE_GAPS
from neura_agent_core.wanted import WANTED_ITEMS
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
    #: Features FiveNeurals may switch off for one shop (ADR-0065): a key, which
    #: starts with this agent's key, to the words the admin reads, a name and
    #: what it does. An agent without one leaves this out.
    switches: dict[str, tuple[str, str]] = {}
    #: What the admin is told when a switch goes off and on again (ADR-0065:
    #: *Turn off asks first*), by switch key: the question (``{shop}`` is the
    #: shop's name), what happens while it is off, and the line under *On again
    #: since*. A switch without them gets general words.
    switch_notes: dict[str, tuple[str, str, str]] = {}
    #: Which of the console's own pages each switch pauses, by each page's name in
    #: the shared core (``page_gaps``), so the console can say *Paused* without
    #: naming this agent (ADR-0065 §4).
    pauses: dict[str, tuple[str, ...]] = {}
    #: A job kind the console may book to run now, by the name of the console
    #: page it fills (``calendar_plans``): *Make it again* asks for a plan at
    #: once without the API naming this agent (ADR-0072 §5). An agent without
    #: one leaves this out.
    on_demand: dict[str, str] = {}


MANIFEST = AgentManifest(
    key="grow",
    name="NEURA-GROW",
    version="0.1.0",
    description=(
        "The marketing agent. Three pages: Missing from your pages and "
        "Shoppers asked for, found once a night in the shop's chats, and the "
        "Marketing calendar, a campaign plan 21 days before each date the shop "
        "keeps. Read-only; writes nothing to the shop and sends nothing to "
        "anyone."
    ),
    # None: GROW reads NEURA's own record of the shop's chats and synced
    # catalogue, and never calls the shop.
    requires_capabilities=frozenset(),
    route_prefix="/v1/grow",
    chat=False,
    # The night run (neura_agent_grow.jobs): the night check reads the shop's
    # chats, and the calendar step writes the plans that are due.
    daily_job="grow.gaps.scan",
    # Each GROW feature that spends money has its own switch (R51, ADR-0072 §5).
    switches={
        "grow.gaps": (
            # R65: the switch is the check, which fills both GROW pages.
            "The night AI check",
            "Once a night, AI reads the shop's new chats to fill Missing from your "
            "pages and Shoppers asked for.",
        ),
        "grow.calendar": (
            "The calendar's AI plans",
            "21 days before each date the shop keeps on its Marketing calendar, AI "
            "writes a campaign plan. Make it again asks for another.",
        ),
    },
    # The night check's words are the approved ones (board 61); the calendar's
    # are Claude's (ADR-0073).
    switch_notes={
        "grow.gaps": (
            "Turn off the night check for {shop}?",
            "While it is off, no chat is read and no AI is used. Chats from that time are "
            "never read later. What was already found stays on the shop's page, marked "
            "Paused. The shop can't turn it back on.",
            "It reads chats from now on, not the ones from while it was off.",
        ),
        "grow.calendar": (
            "Turn off the calendar's AI plans for {shop}?",
            "While it is off, no plan is made and no AI is used, and the shop can't press "
            "Make it again. Its dates and the plans already made stay on its Marketing "
            "calendar, marked Paused. The shop can't turn it back on.",
            "Plans that are due are made again from the next night.",
        ),
    },
    # One night check finds both pages' rows (ADR-0068 §8); the calendar's own
    # switch pauses its plans.
    pauses={"grow.gaps": (PAGE_GAPS, WANTED_ITEMS), "grow.calendar": (CALENDAR_PLANS,)},
    # Make it again (neura_agent_grow.jobs.CalendarPlansHandler).
    on_demand={CALENDAR_PLANS: "grow.calendar.plans"},
)

__all__ = ["MANIFEST", "AgentManifest"]
