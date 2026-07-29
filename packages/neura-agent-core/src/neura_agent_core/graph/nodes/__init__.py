"""Nodes every agent inherits.

`neura-agent-core` supplies the machinery; an agent supplies its graph, its
prompts and its tools. Nothing here knows which agent it is running.
"""

from neura_agent_core.graph.nodes.act import act, proposals_of, propose
from neura_agent_core.graph.nodes.escalate import escalate
from neura_agent_core.graph.nodes.retrieve import retrieve
from neura_agent_core.graph.nodes.verify import Groundedness, verify

__all__ = [
    "Groundedness",
    "act",
    "escalate",
    "proposals_of",
    "propose",
    "retrieve",
    "verify",
]
