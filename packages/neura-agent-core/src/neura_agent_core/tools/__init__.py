"""The tool layer — declaration, registration, capability filtering, execution.

Everything dangerous about a tool is declared in code here and enforced by
``neura_agent_core.policy``. Nothing about a tool's safety is described to the
model and hoped for.
"""

from neura_agent_core.tools.executor import ToolInvocation, execute
from neura_agent_core.tools.registry import ToolRegistrationError, ToolRegistry
from neura_agent_core.tools.spec import (
    DEFAULT_TIMEOUT_S,
    SessionIdentity,
    ToolContext,
    ToolSpec,
    tool,
)

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "SessionIdentity",
    "ToolContext",
    "ToolInvocation",
    "ToolRegistrationError",
    "ToolRegistry",
    "ToolSpec",
    "execute",
    "tool",
]
