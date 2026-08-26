"""The nodes unique to SELL.

Seven. Everything else in the graph — ``guard``, ``retrieve``, ``act``,
``verify``, ``escalate``, ``blocked`` — comes from ``neura-agent-core`` and is
shared with every agent that will ever be built here.

That ratio is the expandability claim from agent-runtime.md §7 tested for the
first time by an agent it was not written for. SELL supplies its own
understanding of what a message means (``route``), what to look up (``plan``),
**what may be recommended at all** (``shortlist``), how to say it (``compose``),
when to commit to it (``respond``), how to decline without occupying a person
(``decline``), and how to say "we do not carry that" honestly (``no_match``).

The machinery that authorises, checks and hands over is not its to reimplement,
and it could not weaken those parts if it wanted to.

``shortlist`` is the one with no CARE counterpart, and it is where the product's
central claim is made true rather than asserted.
"""

from neura_agent_sell.nodes.compose import compose
from neura_agent_sell.nodes.decline import decline
from neura_agent_sell.nodes.no_match import no_match
from neura_agent_sell.nodes.plan import plan
from neura_agent_sell.nodes.respond import respond
from neura_agent_sell.nodes.route import (
    COMPARE,
    DECLINE_MIN_CONFIDENCE,
    MIN_CONFIDENCE,
    NEEDS_PERSON,
    OUT_OF_SCOPE,
    RECOMMEND,
    Route,
    route,
)
from neura_agent_sell.nodes.shortlist import MAX_CANDIDATES, reached_the_catalogue, shortlist

__all__ = [
    "COMPARE",
    "DECLINE_MIN_CONFIDENCE",
    "MAX_CANDIDATES",
    "MIN_CONFIDENCE",
    "NEEDS_PERSON",
    "OUT_OF_SCOPE",
    "RECOMMEND",
    "Route",
    "compose",
    "decline",
    "no_match",
    "plan",
    "reached_the_catalogue",
    "respond",
    "route",
    "shortlist",
]
