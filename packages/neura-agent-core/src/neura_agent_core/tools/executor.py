"""Running an authorised tool.

Deliberately small, and deliberately *after* the policy engine: this module has
no opinion about whether a call is allowed. It runs what it is handed, bounds
how long it may take, and makes sure nothing a tool does can escape as an
unhandled exception.

The bound matters. A tool calls a merchant's store over HTTP, and a store having
a bad day must not hold a shopper's chat open indefinitely — the agent answering
"I couldn't reach the store, let me get a human" in five seconds is a better
outcome than a spinner.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from neura_agent_core.tools.spec import ToolContext, ToolSpec
from neura_commerce import AdapterError
from neura_core import get_logger

log = get_logger(__name__)


class Authorisation(Protocol):
    """What this module needs to know about a policy decision — and no more.

    A Protocol rather than an import, because ``policy`` depends on ``tools``
    and the reverse would be a cycle. Structural matching means
    ``policy.Decision`` satisfies this without either module knowing about the
    other, which is the same reason ``CommerceAdapter`` is a Protocol.
    """

    @property
    def allowed(self) -> bool: ...

    @property
    def arguments(self) -> BaseModel | None: ...


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """What one tool call did. Recorded whether it worked or not."""

    tool_name: str
    ok: bool
    value: Any = None
    error: str | None = None
    latency_ms: int = 0
    #: Propagated from the tool's declaration, never inferred from the result.
    #: A response derived from this may not enter the semantic cache
    #: (llm-abstraction.md §7).
    pii_output: bool = False

    def as_model_message(self) -> str:
        """What the model sees. On failure it is told plainly, so it can
        escalate rather than invent a plausible answer."""
        if self.ok:
            return str(self.value)
        return f"{self.tool_name} failed: {self.error}"


async def execute(spec: ToolSpec, decision: Authorisation, ctx: ToolContext) -> ToolInvocation:
    """Run an authorised tool call.

    Requires an ``ALLOW`` decision. Calling this with anything else is a
    programming error and raises rather than running — a tool that executes on
    an unauthorised decision would make the entire policy engine decorative.
    """
    if not decision.allowed or decision.arguments is None:
        raise ValueError(
            f"execute() called for {spec.name!r} with an unauthorised decision; "
            "only a call the policy engine allowed may run"
        )

    started = time.perf_counter()
    arguments = decision.arguments.model_dump()

    try:
        value = await asyncio.wait_for(spec.fn(**arguments, ctx=ctx), timeout=spec.timeout_s)
    except TimeoutError:
        return _failed(spec, started, f"timed out after {spec.timeout_s}s")
    except AdapterError as exc:
        # The store said no, or could not be reached. Expected often enough that
        # it is not an incident — the agent degrades and, if it matters,
        # escalates.
        return _failed(spec, started, f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        # A bug in a tool must not take down the conversation. Logged loudly
        # because unlike the branches above, this one is ours.
        log.exception("tool_crashed", tool=spec.name, tenant_id=ctx.tenant_id)
        return _failed(spec, started, f"unexpected error: {type(exc).__name__}")

    invocation = ToolInvocation(
        tool_name=spec.name,
        ok=True,
        value=value,
        latency_ms=_elapsed_ms(started),
        pii_output=spec.pii_output,
    )
    log.info(
        "tool_executed",
        tool=spec.name,
        latency_ms=invocation.latency_ms,
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
    )
    return invocation


def _failed(spec: ToolSpec, started: float, error: str) -> ToolInvocation:
    log.warning("tool_failed", tool=spec.name, error=error)
    return ToolInvocation(
        tool_name=spec.name,
        ok=False,
        error=error,
        latency_ms=_elapsed_ms(started),
        pii_output=spec.pii_output,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
