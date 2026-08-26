"""The MCP methods, over SELL's real tool registry.

**The registry is the real one** — the same `build_registry()` a conversation
uses, filtered by the same `available_for(ctx)`, authorised by the same
`PolicyEngine`, executed by the same `execute()`. That is the entire point of
this surface being cheap ([blueprint §4.1](../../../../../docs/business/blueprint-v2.md):
*marginal cost, not new construction*), and it is also what makes it safe: there
is no second, more permissive path to a merchant's store.

Re-implementing the tools here "for MCP" would have produced exactly the failure
`evals/target.py` exists to prevent for CARE — a second agent nobody measures,
which passes on the day the real one breaks.

## What an external agent may reach, and what it may not

`MCP_TOOLS` is an **allowlist**, not a subtraction. A tool added to `SELL_TOOLS`
later is not exposed to third parties until somebody names it there, so the
default for a new tool is private. `escalate_to_human` is excluded: there is no
human in an MCP session to escalate to, and a tool that files into a merchant's
support queue on a bot's say-so is a denial-of-service surface with a friendly
name.

## Three things this deliberately does not have

**No session state.** Each request carries its own key and is resolved to a
tenant from scratch. MCP has an `initialize` handshake, and honouring it as
*state* would mean a server-side session an unauthenticated request could later
attach to. The handshake is answered; nothing is remembered.

**No `resources/subscribe`, no server-initiated messages.** Both are in the
protocol and both require the server to push, which means holding a connection
per external agent. Nothing needs it yet, and a capability advertised but
unimplemented is worse than one absent — a client will try it.

**No sampling.** MCP lets a server ask the *client's* model to generate
something. Accepting that would put someone else's model inside our request
path, on a merchant's data, with no eval and no `verify`. It is not declined
politely at runtime; the capability is simply never advertised.
"""

from __future__ import annotations

from typing import Any

from neura_agent_core.policy import PolicyEngine
from neura_agent_core.tools import ToolContext, ToolSpec, execute
from neura_agent_sell.mcp import protocol
from neura_agent_sell.tools import MCP_TOOLS, build_registry
from neura_core import get_logger

log = get_logger(__name__)

#: The protocol revision this server implements.
#:
#: **Pinned and recorded rather than negotiated freely.** A server that echoes
#: whatever revision a client asks for is claiming conformance it has not been
#: tested against. What happens when the specification moves — how long a
#: superseded revision is served, and how a connected agent is told — is open
#: question **P9**, and it is unanswered.
#:
#: This constant is not the specification. Confirm it against the spec at build
#: time; this file is not the place to learn what MCP requires.
PROTOCOL_VERSION = "2025-06-18"

SERVER_NAME = "neura-sell"
SERVER_VERSION = "0.1.0"

#: A conversation id for the audit trail. An MCP call is not a conversation and
#: pretending otherwise would put rows in the conversation tables that no
#: shopper ever had — but the policy engine records every decision against one,
#: and an unattributed decision is one nobody can find later.
MCP_CONVERSATION_PREFIX = "mcp_"


class McpServer:
    """One process-wide server. Holds no per-caller state, by design."""

    def __init__(self) -> None:
        # Built once. The registry is about what exists in this deployment;
        # *availability* is decided per request from the caller's context.
        self._registry = build_registry()
        self._policy = PolicyEngine(self._registry)

    # ── Dispatch ─────────────────────────────────────────────────────────────

    async def handle(self, message: Any, ctx: ToolContext) -> dict[str, Any] | None:
        """One JSON-RPC message. ``None`` means "this was a notification".

        Every method is dispatched with the caller's :class:`ToolContext`
        already resolved from their key. There is no method that can widen it,
        because none of them takes a tenant, a store or a scope as a parameter —
        an external agent cannot ask about a catalogue that is not the one their
        key names, since there is nowhere in the protocol to say so.
        """
        if not isinstance(message, dict):
            return protocol.invalid_request(None, "A JSON-RPC message must be an object.")

        request_id = message.get("id")
        method = message.get("method")

        if message.get("jsonrpc") != protocol.VERSION:
            return protocol.invalid_request(request_id, "Expected jsonrpc 2.0.")
        if not isinstance(method, str):
            return protocol.invalid_request(request_id, "Missing method.")

        # A notification expects no response and must not get one. Answering it
        # is a violation a lenient client tolerates and a strict one does not —
        # the worst kind, because it works in testing.
        if protocol.is_notification(message):
            log.info("mcp_notification", method=method, tenant_id=ctx.tenant_id)
            return None

        params = message.get("params") or {}
        if not isinstance(params, dict):
            return protocol.invalid_params(request_id, "params must be an object.")

        try:
            handler = self._method(method)
            if handler is None:
                return protocol.method_not_found(request_id, method)
            return protocol.result(request_id, await handler(params, ctx))
        except protocol.JsonRpcError as exc:
            return protocol.error(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:
            # Logged in full, reported as a generic internal error. A stack
            # trace or an adapter's message reaching a third party's AI agent
            # describes the merchant's infrastructure to a stranger.
            log.error(
                "mcp_handler_failed",
                method=method,
                tenant_id=ctx.tenant_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return protocol.error(request_id, protocol.INTERNAL_ERROR, "Internal error.")

    def _method(self, name: str) -> Any:
        return {
            "initialize": self._initialize,
            "ping": self._ping,
            "tools/list": self._tools_list,
            "tools/call": self._tools_call,
        }.get(name)

    # ── Methods ──────────────────────────────────────────────────────────────

    async def _initialize(self, params: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        """The handshake. Answered, and nothing is remembered.

        The client's requested version is logged rather than echoed. Echoing it
        would claim conformance to whatever it asked for; the honest answer is
        the one revision this server was written against, and a client that
        cannot work with it should find that out at the handshake rather than at
        the third call.

        `capabilities` advertises `tools` only. Not `resources` — the feed is a
        separate, cacheable, public surface and putting it here would give it a
        second access path with different rules. Not `prompts`, `sampling`, or
        `logging`: a capability advertised and unimplemented is worse than one
        absent, because a client will try it.
        """
        requested = params.get("protocolVersion")
        if requested and requested != PROTOCOL_VERSION:
            log.info(
                "mcp_version_mismatch",
                requested=requested,
                serving=PROTOCOL_VERSION,
                tenant_id=ctx.tenant_id,
            )

        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "This server exposes one merchant's product catalogue, read-only. "
                "Every result is that store's own data. It cannot place orders, "
                "modify anything, or read customer or order information."
            ),
        }

    async def _ping(self, params: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        return {}

    async def _tools_list(self, params: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        """What this caller's store can actually do.

        Filtered twice, and the order matters. `available_for(ctx)` drops tools
        whose capabilities the merchant's store does not declare, then
        `MCP_TOOLS` drops the ones no external agent should see. A store with no
        live inventory feed does not merely fail `check_stock` — it never learns
        the tool exists, which is a stronger property than refusing the call.
        """
        return {
            "tools": [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "inputSchema": spec.json_schema(),
                }
                for spec in self._exposed(ctx)
            ]
        }

    async def _tools_call(self, params: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        """Authorise, then execute. Never the other way round.

        The whole of this method's safety is that `self._policy.authorise` runs
        first and `execute` refuses any decision that is not `ALLOW`. That is
        the same path a conversation takes — eight checks, outside any model —
        and the fact that the *caller* here is an AI agent rather than our own
        changes nothing about it.
        """
        name = params.get("name")
        arguments = params.get("arguments") or {}

        if not isinstance(name, str):
            raise protocol.JsonRpcError(protocol.INVALID_PARAMS, "Missing tool name.")
        if not isinstance(arguments, dict):
            raise protocol.JsonRpcError(protocol.INVALID_PARAMS, "arguments must be an object.")

        # Resolved from the exposed set, not from the registry. A tool that
        # exists for conversations but is not exposed to third parties reports
        # as unknown rather than as refused: "that tool is not available here"
        # and "you may not call that tool" tell a caller different things, and
        # only the first is true.
        #
        # Taking the spec from this lookup rather than re-fetching it from the
        # registry also means there is no second, unfiltered path to a ToolSpec
        # in this method — the check and the thing checked are the same object.
        spec = next((s for s in self._exposed(ctx) if s.name == name), None)
        if spec is None:
            raise protocol.JsonRpcError(protocol.INVALID_PARAMS, f"Unknown tool: {name}")

        decision = self._policy.authorise(name, arguments, ctx)

        if not decision.allowed:
            log.info(
                "mcp_tool_refused",
                tool=name,
                tenant_id=ctx.tenant_id,
                outcome=decision.outcome.value,
                check=decision.check.value if decision.check else None,
            )
            # An MCP tool error, not a JSON-RPC error. The protocol distinguishes
            # "the call failed" from "the request was malformed", and a refusal
            # is the first — the caller's agent can read it and try something
            # else, which a transport-level error would not let it do.
            return _tool_error(f"Refused: {decision.reason}")

        invocation = await execute(spec, decision, ctx)

        if not invocation.ok:
            log.warning("mcp_tool_failed", tool=name, tenant_id=ctx.tenant_id)
            # The tool's own error text, which is written for a model to read
            # and says nothing about our infrastructure. An adapter exception
            # would say plenty, and is caught in `handle` instead.
            return _tool_error(str(invocation.error or "The lookup did not complete."))

        log.info("mcp_tool_called", tool=name, tenant_id=ctx.tenant_id)
        return {
            "content": [{"type": "text", "text": str(invocation.value)}],
            "isError": False,
        }

    def _exposed(self, ctx: ToolContext) -> list[ToolSpec]:
        """The tools this caller may see: available for their store, and public."""
        return [spec for spec in self._registry.available_for(ctx) if spec.name in MCP_TOOLS]


def _tool_error(message: str) -> dict[str, Any]:
    """A failed tool call, in MCP's own shape rather than JSON-RPC's."""
    return {"content": [{"type": "text", "text": message}], "isError": True}


__all__ = ["MCP_CONVERSATION_PREFIX", "PROTOCOL_VERSION", "SERVER_NAME", "McpServer"]
