"""Running SELL for a real shopper, over a real transport.

The sibling of ``evals/target.py``, and the resemblance is the point: that
module exists so ``make eval`` measures the agent a shopper talks to, and this
one exists so a shopper talks to the agent ``make eval`` measures. Both build
their runtime through :func:`build_runtime` and invoke the same compiled graph.

Three things this adds that an eval case does not have:

* **A real audit sink**, so a ``guard`` block reaches the append-only log.
* **The tenant's ceilings**, from ``resolve_runtime_policy`` — a tenant over its
  hard budget gets an empty tool allowlist and hands over (ADR-0015).
* **A retriever**, so a served conversation reaches the merchant's indexed
  catalogue rather than answering from tool calls alone.

**No LangGraph checkpointer**, for CARE's reason unchanged: the checkpointer
resumes a turn interrupted mid-node, and nothing in this deployment picks a
half-finished thread back up. Writing a checkpoint after every node so that
nothing ever reads it is the exact shape of failure this project keeps repaying.
"""

from __future__ import annotations

from typing import Any

from neura_agent_core.conversations import ConversationState
from neura_agent_core.graph import CONFIG_KEY, initial_state
from neura_agent_core.serving import (
    Citation,
    Progress,
    ProgressKind,
    ProgressSink,
    TurnOutcome,
    TurnRequest,
)
from neura_agent_sell.graph import compile_graph
from neura_agent_sell.manifest import MANIFEST
from neura_agent_sell.runtime import MAX_TOOL_CALLS, build_runtime
from neura_core import get_logger

log = get_logger(__name__)


class SellRunner:
    """NEURA-SELL, wired for serving."""

    def __init__(self) -> None:
        # Compiled once per process. Building the graph per request would put
        # graph construction inside a shopper's latency for no benefit.
        self._graph = compile_graph()

    @property
    def key(self) -> str:
        return MANIFEST.key

    async def run(self, request: TurnRequest) -> TurnOutcome:
        runtime = build_runtime(
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
            adapter=request.adapter,
            llm=request.llm,
            capabilities=request.capabilities,
            scopes=request.scopes,
            identity=request.identity,
            retriever=request.retriever,
            audit=request.audit,
            allowed_tools=request.allowed_tools,
            max_tool_calls=(
                MAX_TOOL_CALLS if request.max_tool_calls is None else request.max_tool_calls
            ),
        )

        # `astream`, always — never `ainvoke` when nobody is listening. One
        # execution path for both transports is what api-design.md §8 requires
        # and what makes the golden suite evidence about REST *and* WebSocket.
        final: dict[str, Any] = {}
        seen_tools: set[str] = set()

        async for mode, chunk in self._graph.astream(
            initial_state(
                tenant_id=request.tenant_id,
                conversation_id=request.conversation_id,
                message=request.message,
                history=request.history,
            ),
            {
                "configurable": {
                    CONFIG_KEY: runtime,
                    "thread_id": request.conversation_id,
                }
            },
            stream_mode=["updates", "values"],
        ):
            if mode == "values":
                final = chunk
            elif mode == "updates" and request.on_progress is not None:
                await _report(chunk, request.on_progress, seen_tools)

        return _outcome(final)


async def _report(update: dict[str, Any], sink: ProgressSink, seen_tools: set[str]) -> None:
    """Turn one node's update into progress frames.

    Node names and tool names only. Never a tool's arguments and never its
    result — a progress channel is the easiest place in a system to leak
    something, because it is the one stream nobody treats as a response body.
    """
    for node, changes in update.items():
        await sink(Progress(kind=ProgressKind.STEP, name=str(node)))

        if not isinstance(changes, dict):
            continue
        for invocation in changes.get("invocations", []) or []:
            name = getattr(invocation, "tool_name", None)
            if name and getattr(invocation, "ok", False) and name not in seen_tools:
                seen_tools.add(name)
                await sink(Progress(kind=ProgressKind.TOOL_CALL, name=str(name)))


def _outcome(final: dict[str, Any]) -> TurnOutcome:
    """Map SELL's final state onto the transport-neutral record.

    Every field is read from a flag the graph set. Nothing is inferred from the
    reply text, for the reason the eval harness does not either: a model can
    apologise politely while a tool ran anyway.
    """
    blocked = bool(final.get("blocked"))
    escalated = bool(final.get("escalated"))
    invocations = final.get("invocations", [])
    usage = final.get("usage", {})

    return TurnOutcome(
        reply=str(final.get("reply", "")),
        state=_state(blocked=blocked, escalated=escalated),
        escalated=escalated,
        blocked=blocked,
        refused=bool(final.get("refused")),
        grounded=final.get("grounded"),
        draft=str(final.get("draft", "")),
        verify_reason=str(final.get("verify_reason", "")),
        intent=final.get("intent"),
        citations=_citations(final),
        tool_calls=sum(1 for i in invocations if i.ok),
        infrastructure_error=final.get("infrastructure_error"),
        prompt_revision=usage.get("prompt_revision"),
        handoff=str(final.get("handoff", "")),
        escalation_reason=str(final.get("escalation_reason", "")),
    )


def _state(*, blocked: bool, escalated: bool) -> ConversationState:
    """Which of the four states this turn ended in."""
    if blocked:
        return ConversationState.BLOCKED
    if escalated:
        return ConversationState.ESCALATED
    return ConversationState.RESOLVED


def _citations(final: dict[str, Any]) -> list[Citation]:
    """The evidence this reply was checked against.

    **Products are cited by id**, which is what makes a SELL reply auditable in
    a way a CARE reply is not: a merchant reading a recommendation can see
    exactly which products it was allowed to name, and compare that to what it
    actually said. These come from ``promises`` — the shortlist — rather than
    from the reply text, so a citation cannot be produced by a model writing one.
    """
    citations: list[Citation] = [
        Citation(type="product", id=str(product_id)) for product_id in final.get("promises", [])
    ]

    for source in final.get("sources", []):
        reference = str(source).split("#", 1)[0]
        source_type, _, source_id = reference.partition(":")
        if source_id:
            citations.append(Citation(type=source_type, id=source_id))

    for invocation in final.get("invocations", []):
        if invocation.ok:
            citations.append(Citation(type="tool", id=invocation.tool_name))

    seen: set[tuple[str, str]] = set()
    unique: list[Citation] = []
    for citation in citations:
        marker = (citation.type, citation.id)
        if marker not in seen:
            seen.add(marker)
            unique.append(citation)
    return unique


def build_runner() -> SellRunner:
    """Entry point the API resolves. Registered in ``pyproject.toml``.

    Discovered rather than imported by name, for the reason the eval target is:
    ``neura-api`` must not learn that an agent called "sell" exists.
    """
    return SellRunner()


__all__ = ["SellRunner", "build_runner"]
