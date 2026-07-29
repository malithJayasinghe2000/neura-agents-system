"""The nodes unique to CARE.

Six. Everything else in the graph — ``retrieve``, ``act``, ``verify``,
``escalate`` — comes from ``neura-agent-core`` and is shared with every agent
that will ever be built here.

That ratio is the expandability claim from agent-runtime.md §7 being true rather
than asserted: an agent supplies its own understanding of what a message means
(``route``), what to look up (``plan``), whether the turn is still answerable
(``triage``), how to say it (``compose``), when to commit to it (``respond``) and
how to say no without occupying a person (``decline``).
The machinery that authorises, checks and hands over is not its to reimplement,
and it could not weaken those parts if it wanted to.
"""

from neura_agent_care.nodes.compose import compose
from neura_agent_care.nodes.decline import decline
from neura_agent_care.nodes.plan import plan
from neura_agent_care.nodes.respond import respond
from neura_agent_care.nodes.route import (
    DECLINE_MIN_CONFIDENCE,
    MIN_CONFIDENCE,
    NEEDS_PERSON,
    ORDER_STATUS,
    OUT_OF_SCOPE,
    POLICY_QA,
    PRODUCT_QA,
    Route,
    route,
)
from neura_agent_care.nodes.triage import triage

__all__ = [
    "DECLINE_MIN_CONFIDENCE",
    "MIN_CONFIDENCE",
    "NEEDS_PERSON",
    "ORDER_STATUS",
    "OUT_OF_SCOPE",
    "POLICY_QA",
    "PRODUCT_QA",
    "Route",
    "compose",
    "decline",
    "plan",
    "respond",
    "route",
    "triage",
]
