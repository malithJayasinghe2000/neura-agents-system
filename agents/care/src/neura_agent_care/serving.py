"""Running CARE for a real shopper, over a real transport.

The sibling of ``evals/target.py``, and the resemblance is the point. That module
exists so ``make eval`` measures the agent a shopper talks to rather than a
convenient reimplementation of it; this one exists so a shopper talks to the
agent ``make eval`` measures. **Both build their runtime through
:func:`build_runtime` and invoke the same compiled graph**, and
``tests/unit/test_serving.py`` asserts that a served turn and an evaluated turn
are equipped identically for an unconfigured tenant — same tools, same ceiling,
same guard state, same prompts. Without that assertion "the eval measures what we
ship" is a claim rather than a property, and this project has already recorded
what happens when a measurement mode differs from the real thing in more than one
respect (``make eval-guard-off``, milestone 1.12).

Three things this adds that an eval case does not have, and each is a control
that existed as a seam until now:

* **A real audit sink.** A ``guard`` block writes ``guard.block`` to the
  append-only log. With ``None`` it writes nowhere, and ADR-0012's whole defence
  — the merchant learns in aggregate — is a promise about code nobody ran
  (open question **S5**).
* **The tenant's ceilings.** ``allowed_tools`` and ``max_tool_calls`` arrive from
  ``resolve_runtime_policy``, so a tenant over its hard budget gets an empty tool
  allowlist and hands over (ADR-0015). For an unconfigured tenant they are
  exactly ``build_runtime``'s defaults, which is why this does not move the
  agent.
* **A retriever.** Eval cases answer from fixtures with no vector store; a served
  conversation reaches the merchant's indexed catalogue and policy pages.

**No LangGraph checkpointer, and that is deliberate.** The checkpointer's purpose
is resuming a turn interrupted mid-node, and nothing in this deployment would
pick a half-finished thread back up — there is no worker and no queue until 1.17.
Writing a checkpoint after every node so that nothing ever reads it is the exact
shape of failure this milestone exists to repay. Conversation continuity comes
from the transcript (``neura_agent_core.conversations``), the forensic trail from
the audit log, and a turn lost to a crash is retried by the client under its
idempotency key. The checkpointer stays in the tree, is still the only
tenant-aware one, and is still exercised by the integration suite.
"""

from __future__ import annotations

from typing import Any

from neura_agent_care.graph import compile_graph
from neura_agent_care.manifest import MANIFEST
from neura_agent_care.runtime import MAX_TOOL_CALLS, build_runtime
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
from neura_core import get_logger

log = get_logger(__name__)


class CareRunner:
    """NEURA-CARE, wired for serving."""

    def __init__(self) -> None:
        # Compiled once per process. Building the graph per request would put
        # graph construction inside a shopper's latency for no benefit, and the
        # compiled object holds nothing request-specific — every per-turn
        # dependency travels in the `Runtime`.
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
        # and what makes the golden suite evidence about REST *and* WebSocket
        # (ADR-0016 §4). The two stream modes are asked for together: `updates`
        # names the node that just ran, `values` carries the accumulated state,
        # and the last of those is the final state `ainvoke` would have returned.
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

    Node names and tool names only. Never a tool's arguments — they carry the
    shopper's order references — and never its result, which is the merchant's
    customer data. A progress channel is the easiest place in a system to leak
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
    """Map CARE's final state onto the transport-neutral record.

    Every field is read from a flag the graph set. Nothing is inferred from the
    reply text, for the same reason the eval harness does not: a model can
    apologise politely while a tool ran anyway, and a canned refusal is easy to
    produce without having noticed anything.
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
        intent=final.get("intent"),
        citations=_citations(final),
        tool_calls=sum(1 for i in invocations if i.ok),
        infrastructure_error=final.get("infrastructure_error"),
        prompt_revision=usage.get("prompt_revision"),
        handoff=str(final.get("handoff", "")),
        escalation_reason=str(final.get("escalation_reason", "")),
    )


def _state(*, blocked: bool, escalated: bool) -> ConversationState:
    """Which of the four states this turn ended in.

    ``blocked`` is tested first: a blocked turn never reaches the branches that
    set ``escalated``, but ordering the test rather than relying on that keeps
    the mapping true if a future graph changes its mind.

    ``AWAITING_CUSTOMER`` is never returned, and that is a statement about CARE
    rather than an omission here. CARE has no node that asks a clarifying
    question and stops — an unclear turn escalates instead (open question A5).
    The value exists in the contract because the state belongs to the API, not
    to one agent, and inventing a turn that produced it would be inventing
    behaviour.
    """
    if blocked:
        return ConversationState.BLOCKED
    if escalated:
        return ConversationState.ESCALATED
    return ConversationState.RESOLVED


def _citations(final: dict[str, Any]) -> list[Citation]:
    """The evidence this reply was checked against.

    Two kinds, and they are deliberately not made to look alike:

    * **Retrieved documents**, from ``sources``, already in the stable
      ``type:id#chunk`` form the retriever produces. Cited by type and id, so a
      merchant can find the policy page an answer came from.
    * **Tools**, by name. A tool citation says which lookup produced the
      evidence, not which record came back — the record is customer data and
      belongs in the audit log, under its retention policy, not in a response
      body that a merchant's front end may log.
    """
    citations: list[Citation] = []

    for source in final.get("sources", []):
        reference = str(source).split("#", 1)[0]
        source_type, _, source_id = reference.partition(":")
        if source_id:
            citations.append(Citation(type=source_type, id=source_id))

    for invocation in final.get("invocations", []):
        if invocation.ok:
            citations.append(Citation(type="tool", id=invocation.tool_name))

    # Order-preserving de-duplication: a policy answer commonly retrieves three
    # chunks of one page, and citing it three times tells an integrator nothing
    # while looking like three independent sources.
    seen: set[tuple[str, str]] = set()
    unique: list[Citation] = []
    for citation in citations:
        marker = (citation.type, citation.id)
        if marker not in seen:
            seen.add(marker)
            unique.append(citation)
    return unique


def build_runner() -> CareRunner:
    """Entry point the API resolves. Registered in ``pyproject.toml``.

    Discovered rather than imported by name, for the same reason the eval target
    is: ``neura-api`` must not learn that an agent called "care" exists
    (AGENTS.md, "Add an agent").
    """
    return CareRunner()


__all__ = ["CareRunner", "build_runner"]
