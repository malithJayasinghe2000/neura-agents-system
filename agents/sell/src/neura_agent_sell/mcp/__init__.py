"""The MCP server — SELL's second surface, and its strangest one.

An external AI agent — someone else's, not ours — connects and reads the
merchant's catalogue. **No graph, no prompt, no model call of ours, no `guard`,
no `verify`.** Those nodes exist to police *our* reasoning; here the reasoning
belongs to a system we do not run and cannot inspect.

What is left is the part that was never a prompt: capability filtering, scope
checks, tenant isolation, the audit log, and read-only tools. That is the whole
security argument for this surface, and it is deliberately *not* CARE's. CARE's
argument is "a persuaded model achieves nothing, because no tool that changes a
store was ever registered". Here there is no model of ours to persuade, so the
argument is only ever: nothing reachable can write, and nothing reachable
crosses a tenant.

    protocol.py   JSON-RPC 2.0 framing — the wire format, and nothing else
    server.py     the methods, over SELL's real tool registry

**This is not the MCP specification and must not be read as one.** The revision
is pinned, recorded, and confirmed against the spec at build time — registered
as open question **P9**, which also owns what happens when the spec moves.
"""

from neura_agent_sell.mcp.protocol import (
    JsonRpcError,
    error,
    invalid_params,
    method_not_found,
    parse_error,
    result,
)
from neura_agent_sell.mcp.server import PROTOCOL_VERSION, SERVER_NAME, McpServer

__all__ = [
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "JsonRpcError",
    "McpServer",
    "error",
    "invalid_params",
    "method_not_found",
    "parse_error",
    "result",
]
