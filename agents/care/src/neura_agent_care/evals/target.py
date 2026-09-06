"""Running CARE against a golden case.

Milestone 1.4 built the eval harness *before* the agent and left ``EvalTarget``
as the seam, with a ``NotImplementedTarget`` that returned an explicit error so a
run could never be mistaken for a real result. This is what plugs into it. From
here, ``make eval`` measures an agent rather than measuring the harness.

Two things it must get right, and they pull in opposite directions:

* **It must run the real graph.** A target that reimplemented the flow "for
  testing" would grade a second agent that no shopper ever talks to, and would
  pass on the day the real one broke. So this builds CARE exactly as a served
  conversation would, through :func:`build_runtime`, and invokes the compiled
  graph.
* **It must be reproducible.** The store is fixtures, not the live shop, and the
  temperature is pinned by the nodes. A suite whose failures are ambiguous
  between "the agent regressed" and "somebody edited a product" is one nobody
  acts on.

**Authorisation comes from the case's session, and only from there.**
``verified_customer_id`` is what makes an order readable; a case that does not
set it gets an anonymous shopper, which is the correct default and is what makes
the enumeration cases meaningful.
"""

from __future__ import annotations

from typing import Any

from neura_evals.dataset import EvalCase, FixtureMode
from neura_evals.target import AgentResponse, ToolInvocation

from neura_agent_care.evals.store import ALL_CAPABILITIES, FIXTURE_DIR, load_store
from neura_agent_care.graph import compile_graph
from neura_agent_care.runtime import build_runtime
from neura_agent_care.tools import TOOL_SCOPES
from neura_agent_core.audit import AuditEvent, InMemoryAuditLog
from neura_agent_core.evidence import ReplayAdapter, ReplayRetriever, read_artefact
from neura_agent_core.graph import CONFIG_KEY, initial_state, total_cost, total_tokens
from neura_agent_core.policy import Outcome
from neura_agent_core.tools import SessionIdentity
from neura_core import get_logger

log = get_logger(__name__)

#: One tenant for the whole suite. Isolation is proved by the RLS integration
#: tests against real PostgreSQL, not here — an eval that also tried to test
#: tenancy would be measuring two things and diagnosing neither.
EVAL_TENANT = "tn_eval_care"


class CareTarget:
    """NEURA-CARE, wired for evaluation."""

    def __init__(self, llm: Any, *, tenant_id: str = EVAL_TENANT) -> None:
        self._llm = llm
        self._tenant_id = tenant_id
        # Compiled once. Building the graph per case would measure graph
        # construction as if it were agent latency.
        self._graph = compile_graph()

    @property
    def name(self) -> str:
        return f"care@{getattr(self._llm, 'role_map_name', 'unknown')}"

    async def run(self, case: EvalCase) -> AgentResponse:
        """One case, start to finish, through the real graph."""
        store, capabilities, retriever = _store_for(case, self._tenant_id)

        # A real audit sink, in memory. `guard` writes its security event here,
        # so a blocked case can be checked against the RECORD rather than
        # against the reply text — the same argument that makes the injection
        # suite assert on the policy engine's decisions. A canned refusal is
        # easy to produce without having noticed anything.
        audit = InMemoryAuditLog()

        runtime = build_runtime(
            tenant_id=self._tenant_id,
            conversation_id=f"cnv_{case.id}",
            adapter=store,
            llm=self._llm,
            capabilities=capabilities,
            scopes=TOOL_SCOPES,
            identity=_identity(case),
            # No retriever for an invented case. The catalogue is reachable
            # through tools here, and standing up pgvector per case would make
            # the suite depend on a database to answer a question about the
            # agent's reasoning. Retrieval has its own measured smoke test
            # (`make rag-check`).
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
            log.error("care_case_crashed", case_id=case.id, error=str(exc))
            return AgentResponse(reply="", error=f"CARE raised: {type(exc).__name__}: {exc}")

        return _response(final, audit)


def _store_for(case: EvalCase, tenant_id: str) -> tuple[Any, frozenset[Any], Any]:
    """The store this case runs against, and what the store could do — [ADR-0034] §5.

    Two modes, chosen by the case and never inferred. An **overlay** case gets
    exactly what it has always got: the base fixture with its own files layered
    on. A **replay** case gets the boundary its turn recorded, and the base
    fixture is not loaded at all — mixing them would put July's three invented
    products into a catalogue beside a merchant's real ones.

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


def _identity(case: EvalCase) -> SessionIdentity:
    """What the case says has been *proven* about the shopper.

    Only ``verified_customer_id``. There is deliberately no way for a case to
    pre-verify an arbitrary order reference: how an anonymous shopper proves they
    own order 1001 is open question C1, undecided, and a dataset that assumed an
    answer would bake the assumption into every future run.
    """
    return SessionIdentity(customer_external_id=case.session.verified_customer_id)


def _response(final: dict[str, Any], audit: InMemoryAuditLog) -> AgentResponse:
    """Map CARE's final state onto what the harness scores.

    The mapping that matters is ``authorised``. It is read from the **policy
    engine's decisions**, not from whether a tool produced output and not from
    the text of the reply. That is the whole design of the injection suite: a
    reply can sound like a refusal while a tool was quietly invoked, so
    ``injection_resistance`` is asserted against what the engine recorded
    (evaluation-strategy.md §3).

    ``blocked`` follows the same rule for the same reason, and it is read from
    the **audit log** rather than from the state flag. A node can set
    ``blocked=True`` and forget to record the security event, and the difference
    between those two is the whole of ADR-0012's argument: a block the merchant
    cannot count is not the cheap-and-visible outcome that decision chose, it is
    the cheap-and-invisible one it rejected.
    """
    decisions = final.get("decisions", [])
    refused = {d.tool_name for d in decisions if d.outcome is not Outcome.ALLOW}

    tools_called = [
        ToolInvocation(
            name=invocation.tool_name,
            arguments=invocation.arguments,
            authorised=invocation.tool_name not in refused or invocation.ok,
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
        # "Refused" is narrower than "escalated": the agent declining to act on
        # something it may not do, rather than handing a live question over.
        #
        # Two ways to get here, and they are genuinely different outcomes. The
        # `decline` node sets `refused` on the state directly and does *not*
        # escalate — that is the A5 path, where the question was out of scope and
        # no person was needed. `blocked` does the same, for the S4 path. The
        # third is a policy refusal that ended in a handover. All three are
        # refusals; only the last costs a human.
        refused=bool(final.get("refused")) or (escalated and _was_refused(decisions)),
        **_spend(final),
    )


def _spend(final: dict[str, Any]) -> dict[str, Any]:
    """What the turn cost, as the harness reports it.

    Read from the shared accumulator. Until 2026-08-27 this mapped ``tokens``
    alone, and ``tokens`` was only ``compose``'s share — the router, the planner
    and the verifier were all metered as free, so no report could answer *"what
    would this suite cost on a cloud provider?"*.

    `cost_usd` is ``0`` for a local model **and** for a cloud model with no
    configured price. Set ``LLM_PRICING_JSON`` before reading anything into a
    zero here (CLAUDE.md §4).
    """
    usage = final.get("usage", {})
    return {
        "tokens_used": total_tokens(usage),
        "cost_usd": total_cost(usage),
        "llm_calls": int(usage.get("calls", 0)),
        "structured_repairs": int(usage.get("structured_repairs", 0)),
    }


def _evidence(final: dict[str, Any]) -> list[str]:
    """What the groundedness judge scores the reply against.

    Exactly what ``verify`` was given — successful tool results and retrieved
    context. Handing the judge more than the agent had would grade a different
    conversation.
    """
    evidence = [str(i.value) for i in final.get("invocations", []) if i.ok]
    if context := final.get("context"):
        evidence.append(str(context))
    return evidence


def _was_refused(decisions: list[Any]) -> bool:
    return any(d.outcome in (Outcome.REJECT, Outcome.ESCALATE) for d in decisions)


def build_target(llm: Any) -> CareTarget:
    """Entry point the eval CLI resolves. Registered in ``pyproject.toml``.

    Discovered rather than imported by name: ``neura-evals`` must not learn that
    an agent called "care" exists, for the same reason ``neura-agent-core`` must
    not (AGENTS.md, "Add an agent").
    """
    return CareTarget(llm)


__all__ = ["EVAL_TENANT", "CareTarget", "build_target"]
