"""The graph runtime — an explicit state machine, not an agent loop (ADR-0004).

An agent supplies nodes and edges; this package supplies the shared nodes, the
state, the checkpointer, and a builder that refuses to compile a graph which
could answer without verifying, has no way to escalate, guards too late, or lets
a blocked turn carry on.
"""

from neura_agent_core.graph.builder import (
    SHARED_NODES,
    AgentGraph,
    GraphContractError,
)
from neura_agent_core.graph.nodes import (
    Groundedness,
    act,
    blocked,
    escalate,
    guard,
    proposals_of,
    propose,
    retrieve,
    verify,
)
from neura_agent_core.graph.state import (
    CONFIG_KEY,
    GUARD_ENV_VAR,
    AgentState,
    Runtime,
    guard_enabled_by_default,
    initial_state,
    runtime_of,
)

__all__ = [
    "CONFIG_KEY",
    "GUARD_ENV_VAR",
    "SHARED_NODES",
    "AgentGraph",
    "AgentState",
    "GraphContractError",
    "Groundedness",
    "Runtime",
    "act",
    "blocked",
    "escalate",
    "guard",
    "guard_enabled_by_default",
    "initial_state",
    "proposals_of",
    "propose",
    "retrieve",
    "runtime_of",
    "verify",
]
