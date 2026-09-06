"""Running SELL against a golden case.

Two things it must get right, and they pull in opposite directions:

* **It must run the real graph.** A target that reimplemented the flow "for
  testing" would grade a second agent no shopper talks to, and would pass on the
  day the real one broke. So this builds SELL exactly as a served conversation
  does, through :func:`build_runtime`, and invokes the compiled graph.
* **It must be reproducible.** The store is fixtures, not the live shop, and the
  temperature is pinned by the nodes.

**``authorised`` is read from the policy engine's decisions**, never from
whether a tool produced output and never from the reply text. That is the design
of the injection suite: a reply can sound like a refusal while a tool was quietly
invoked, so ``injection_resistance`` is asserted against what the engine
recorded (evaluation-strategy.md §3).

**And ``recommended`` is read from ``promises``**, not from the reply. The
shortlist is what the graph *permitted*; parsing product names out of prose
would grade the agent on our ability to write a regex over English.
"""

from __future__ import annotations

from typing import Any

from neura_evals.dataset import EvalCase, FixtureMode
from neura_evals.target import AgentResponse, ToolInvocation

from neura_agent_core.audit import AuditEvent, InMemoryAuditLog
from neura_agent_core.evidence import ReplayAdapter, ReplayRetriever, read_artefact
from neura_agent_core.graph import CONFIG_KEY, initial_state, total_cost, total_tokens
from neura_agent_core.policy import Outcome
from neura_agent_core.tools import SessionIdentity
from neura_agent_sell.evals.store import ALL_CAPABILITIES, FIXTURE_DIR, load_store
from neura_agent_sell.graph import compile_graph
from neura_agent_sell.runtime import build_runtime
from neura_agent_sell.tools import TOOL_SCOPES
from neura_core import get_logger

log = get_logger(__name__)

#: One tenant for the whole suite. Isolation is proved by the RLS integration
#: tests against real PostgreSQL, not here — an eval that also tried to test
#: tenancy would be measuring two things and diagnosing neither.
EVAL_TENANT = "tn_eval_sell"


class SellTarget:
    """NEURA-SELL, wired for evaluation."""

    def __init__(self, llm: Any, *, tenant_id: str = EVAL_TENANT) -> None:
        self._llm = llm
        self._tenant_id = tenant_id
        # Compiled once. Building the graph per case would measure graph
        # construction as if it were agent latency.
        self._graph = compile_graph()

    @property
    def name(self) -> str:
        return f"sell@{getattr(self._llm, 'role_map_name', 'unknown')}"

    async def run(self, case: EvalCase) -> AgentResponse:
        """One case, start to finish, through the real graph."""
        store, capabilities, retriever = _store_for(case, self._tenant_id)
        audit = InMemoryAuditLog()

        runtime = build_runtime(
            tenant_id=self._tenant_id,
            conversation_id=f"cnv_{case.id}",
            adapter=store,
            llm=self._llm,
            capabilities=capabilities,
            scopes=TOOL_SCOPES,
            identity=SessionIdentity(customer_external_id=case.session.verified_customer_id),
            # No retriever for an invented case. The catalogue is reachable
            # through tools here, and standing up pgvector per case would make
            # the suite depend on a database to answer a question about the
            # agent's reasoning.
            #
            # A promoted case is the exception, and only when its turn actually
            # retrieved: replaying half a boundary would silently change what the
            # graded turn had in front of it ([ADR-0034] §5).
            retriever=retriever,
            audit=audit,
        )

        try:
            final = await self._graph.ainvoke(
                initial_state(
                    tenant_id=self._tenant_id,
                    conversation_id=f"cnv_{case.id}",
                    message=case.input,
                    history=case.session.history,
                ),
                {"configurable": {CONFIG_KEY: runtime, "thread_id": f"cnv_{case.id}"}},
            )
        except Exception as exc:
            # Reported as an execution failure, which the harness scores as a
            # failed case rather than a plausible empty reply. A crash that
            # scored as "the agent refused" would be the most flattering
            # possible bug.
            log.error("sell_case_crashed", case_id=case.id, error=str(exc))
            return AgentResponse(reply="", error=f"SELL raised: {type(exc).__name__}: {exc}")

        return _response(final, audit)


def _response(final: dict[str, Any], audit: InMemoryAuditLog) -> AgentResponse:
    """Map SELL's final state onto what the harness scores."""
    decisions = final.get("decisions", [])
    refused_tools = {d.tool_name for d in decisions if d.outcome is not Outcome.ALLOW}

    tools_called = [
        ToolInvocation(
            name=invocation.tool_name,
            arguments=invocation.arguments,
            authorised=invocation.tool_name not in refused_tools or invocation.ok,
            error=invocation.error,
        )
        for invocation in final.get("invocations", [])
        # A refused call never ran. Listing it as a tool call would make every
        # correctly-blocked injection case fail its own safety assertion.
        if invocation.ok
    ]

    escalated = bool(final.get("escalated"))
    blocked = bool(final.get("blocked")) and any(
        entry.event_type is AuditEvent.GUARD_BLOCK for entry in audit.for_tenant(EVAL_TENANT)
    )

    return AgentResponse(
        reply=final.get("reply", ""),
        intent=final.get("intent"),
        tools_called=tools_called,
        retrieved_context=_evidence(final),
        escalated=escalated,
        draft=final.get("draft", ""),
        verify_reason=final.get("verify_reason", ""),
        escalation_reason=final.get("escalation_reason", ""),
        infrastructure_error=final.get("infrastructure_error"),
        blocked=blocked,
        pii_leaked=bool(final.get("pii_leaks")),
        # Three ways to be a refusal, and they are different outcomes. `decline`
        # is the A5 path — out of scope, nobody needed. `no_match` is the honest
        # miss. `blocked` is the S4 path. The fourth is a policy refusal that
        # ended in a handover, and only that one costs a human.
        refused=bool(final.get("refused")) or (escalated and _was_refused(decisions)),
        **_spend(final),
    )


def _spend(final: dict[str, Any]) -> dict[str, Any]:
    """What the turn cost, as the harness reports it.

    Read from the accumulator rather than assembled here, and all three fields
    read rather than one. Until 2026-08-27 this mapped `tokens` alone, which was
    itself only ``compose``'s share — so a report could not answer *"what would
    this suite cost on a cloud provider?"*, the question the role map exists for.

    `cost_usd` is ``0`` for a local model **and** for a cloud model with no
    configured price. Set ``LLM_PRICING_JSON`` before reading anything into a
    zero here (CLAUDE.md §4).
    """
    usage = final.get("usage", {})
    return {
        "tokens_used": total_tokens(usage),
        "cost_usd": total_cost(usage),
        "llm_calls": int(usage.get("calls", 0)),
        # Gated at 0.05 and, until now, computed from a field nothing ever set —
        # a green gate derived from no measurement, which is the one number shape
        # this harness exists to refuse.
        "structured_repairs": int(usage.get("structured_repairs", 0)),
    }


def _evidence(final: dict[str, Any]) -> list[str]:
    """What the groundedness judge scores the reply against.

    Exactly what ``verify`` was given — the shortlist and any retrieved context.
    Handing the judge more than the agent had would grade a different
    conversation, and handing it the *unfiltered* tool results would grade the
    agent as though `shortlist` had not run.
    """
    evidence = []
    if context := final.get("context"):
        evidence.append(str(context))
    return evidence


def _was_refused(decisions: list[Any]) -> bool:
    return any(d.outcome in (Outcome.REJECT, Outcome.ESCALATE) for d in decisions)


def _store_for(case: EvalCase, tenant_id: str) -> tuple[Any, frozenset[Any], Any]:
    """The store this case runs against, and what the store could do — [ADR-0034] §5.

    Two modes, chosen by the case and never inferred. An **overlay** case gets
    exactly what it has always got: the base fixture with its own files layered
    on. A **replay** case gets the boundary its turn recorded, and the base
    fixture is not loaded at all — mixing them would put the invented catalogue
    into the same store as a merchant's real one.

    The replayed store's capabilities come from the bundle, so a case captured
    against a store that could not search does not run as though it could.
    """
    if case.fixture_mode is not FixtureMode.REPLAY:
        return load_store(tenant_id, case.fixtures), ALL_CAPABILITIES, None

    # `evidence` is guaranteed present by `EvalCase`'s validator; a replay case
    # without it never parses.
    bundle = read_artefact(FIXTURE_DIR, str(case.evidence))
    replay = ReplayAdapter(bundle, tenant_id=tenant_id)
    retriever = ReplayRetriever(bundle) if bundle.retrieval else None
    return replay, replay.capabilities or ALL_CAPABILITIES, retriever


def build_target(llm: Any) -> SellTarget:
    """Entry point the eval CLI resolves. Registered in ``pyproject.toml``.

    Discovered rather than imported by name: ``neura-evals`` must not learn that
    an agent called "sell" exists.
    """
    return SellTarget(llm)


__all__ = ["EVAL_TENANT", "SellTarget", "build_target"]
