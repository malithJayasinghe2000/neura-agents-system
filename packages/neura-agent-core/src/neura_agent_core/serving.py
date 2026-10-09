"""The seam between a transport and an agent.

Milestone 1.14 needed a way for the API to run *an* agent without knowing which
agents exist. Two such seams already exist and this is the third, built the same
way for the same reason:

* ``neura.agents`` — a manifest, so the API knows an agent is installed.
* ``neura.eval_targets`` — a target, so ``make eval`` can measure it.
* ``neura.agent_runners`` — **this** — so a request can be turned into a turn.

The alternative was ``from neura_agent_care import build_runtime, compile_graph``
in a route handler, which would make adding agent #2 an edit to the API, and
would put an agent's name in the one package that must stay ignorant of them to
sell the same codebase as five products (tenancy-and-packaging.md §2.5).

**What is deliberately *not* here.** No HTTP, no envelopes, no status codes, no
streaming. A runner takes a :class:`TurnRequest` and returns a
:class:`TurnOutcome`; whether that arrived over REST or a WebSocket is not
something an agent is allowed to be able to tell, which is what makes
api-design.md §8's "the transport is never allowed to become a second code path"
structurally true rather than a promise.

**And what is deliberately not *decided* here.** A runner is handed its ceilings
(``allowed_tools``, ``max_tool_calls``), its audit sink and its retriever. It does
not read a tenant's budget, resolve entitlements or open a database session. Those
are the caller's job — ``neura_agent_core`` never learns that tenants have budgets,
for the same reason it never learns an agent's name.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from neura_agent_core.conversations import ConversationState
from neura_agent_core.rag.retrieval import Retriever
from neura_agent_core.tools.spec import SessionIdentity
from neura_domain import Capability

if TYPE_CHECKING:
    # Type-only, for the reason spelled out at length in `graph/state.py`:
    # `neura_agent_core.audit` reads the `audit_log` table out of
    # `graph.schema`, so importing it at module scope from a module the graph
    # may reach first is how a cycle gets created that fires under one import
    # order and not another.
    from neura_agent_core.audit import AuditSink


@dataclass(frozen=True, slots=True)
class Citation:
    """A piece of evidence the reply was checked against.

    ``type`` and ``id`` are what api-design.md §7 promises an integrator, and
    they are what makes grounding visible when a merchant disputes an answer.

    Two sources, and the distinction is stated rather than blurred: a retrieved
    document is cited by ``type:id`` and can be looked up; a tool is cited by
    **name**, which says which lookup produced the evidence and not which record
    came back. The record itself is in the audit log, where it is covered by the
    hash chain and by the retention policy that customer data belongs under.
    """

    type: str
    id: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}


class ProgressKind(StrEnum):
    """What a progress event is about."""

    STEP = "step"
    """A graph node finished. Names the node and nothing else."""

    TOOL_CALL = "tool_call"
    """A tool ran. Names the tool and nothing else — never its arguments, which
    contain the shopper's order references, and never its result, which is the
    merchant's customer data."""


@dataclass(frozen=True, slots=True)
class Progress:
    """One thing that happened during a turn, safe to show a shopper's browser.

    Deliberately two fields. A progress channel is the easiest place in a system
    to leak something: it is the one stream nobody treats as a response body, and
    "just for debugging" is how a tool's arguments end up in a browser's console.
    """

    kind: ProgressKind
    name: str


#: Called as a turn progresses. Awaited, so a transport can write to a socket.
#:
#: **A runner must stream whether or not one is supplied.** Invoking one way when
#: nobody is listening and streaming when somebody is creates two execution paths
#: for one turn — the exact thing api-design.md §8 forbids, and it would make the
#: golden suite evidence about only one of them (ADR-0016 §4).
ProgressSink = Callable[[Progress], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TurnRequest:
    """Everything one turn needs, assembled by the caller.

    Every access-control value in here — ``identity``, ``scopes``,
    ``capabilities``, ``allowed_tools`` — comes from the authenticated request
    and from the tenant's row. None of it is derived from the shopper's message,
    which is what makes AGENTS.md rule 3 true in practice rather than in
    principle.
    """

    tenant_id: str
    conversation_id: str
    message: str

    #: The store, the models, and where retrieval comes from. Typed loosely for
    #: the same reason ``Runtime`` types them loosely: an agent that stubs its
    #: LLM in a test must not have to install a provider to do so.
    adapter: Any
    llm: Any
    capabilities: frozenset[Capability]
    scopes: frozenset[str]

    identity: SessionIdentity = field(default_factory=SessionIdentity)
    history: list[dict[str, str]] = field(default_factory=list)
    retriever: Retriever | None = None

    #: **A served conversation must pass a real sink.** A ``guard`` block with a
    #: ``None`` audit log is a block nobody can count, and countability is most
    #: of what makes blocking defensible rather than merely cheap (ADR-0012).
    #: Optional here only so a unit test can run a runner without a database.
    audit: AuditSink | None = None

    #: The tenancy ceilings, exactly as ``RuntimePolicy.runtime_kwargs()``
    #: produces them. ``None`` for ``allowed_tools`` means every registered
    #: tool; the empty set means none of them, which is how a hard budget
    #: expresses itself (ADR-0015).
    allowed_tools: frozenset[str] | None = None
    max_tool_calls: int | None = None

    #: Where progress events go, or ``None`` to discard them.
    on_progress: ProgressSink | None = None


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """What happened, in terms a transport can serialise.

    A flat record of facts the graph produced. Nothing here is inferred and
    nothing is prettified: ``state`` is derived from the same flags the eval
    harness scores, so a turn that reads as escalated over HTTP is a turn that
    counts as escalated in the suite.
    """

    reply: str
    state: ConversationState
    escalated: bool = False
    blocked: bool = False
    refused: bool = False
    grounded: bool | None = None
    #: The reply as it stood when ``verify`` passed it — **before** rehydration,
    #: so still tokenised. Empty on a turn that produced no draft.
    #:
    #: Two callers need it and neither can use ``reply``. A **shadow** turn has
    #: no ``reply`` at all, because nothing was sent, and what a human grades is
    #: this (agent-runtime.md §6). And a **failed eval case** is undiagnosable
    #: without it — the harness recorded `composed chars=51` and threw the text
    #: away, so open question **E7** meant re-running a twenty-minute suite to
    #: see one sentence. Tokenised is the right form for both: a review queue and
    #: an eval report are read for weeks, and neither should accumulate card
    #: numbers (security-model.md §6.2).
    draft: str = ""
    #: Why ``verify`` said what it said. The other half of E7 — a refusal whose
    #: reason is not recorded is a refusal somebody has to reproduce to argue
    #: with.
    verify_reason: str = ""
    #: Products this reply may *display*, in the order it names them, as flat
    #: display fields. See [ADR-0030]. Empty for every agent that has no cards
    #: and for every turn that recommended nothing, so a transport can render it
    #: unconditionally.
    cards: list[dict[str, str]] = field(default_factory=list)
    intent: str | None = None
    citations: list[Citation] = field(default_factory=list)
    tool_calls: int = 0
    #: Whether any successful tool this turn declared ``pii_output``.
    #:
    #: A property of the tool's *declaration*, not of its result — no argument
    #: and no returned record is anywhere near this field, which is why it may
    #: exist on an object a transport can see. It exists so that
    #: `neura-agent-core` can refuse to put customer data in a git repository
    #: (ADR-0034 §8) **without holding a list of tool names**, which would be an
    #: agent's knowledge living in the engine and would silently omit the next
    #: agent's PII-bearing tool.
    #:
    #: No route reads it. It travels from the graph to `shadow_evidence`.
    pii_output: bool = False
    #: Set when the provider was unreachable — Ollama down, a cloud API
    #: refusing. **Not an agent decision**, and a caller that scores it as one
    #: repeats the bug that reported intent accuracy 0.00 for a dead server
    #: (open question E6).
    infrastructure_error: str | None = None
    #: Which prompt revision produced the reply, when the agent stamps one.
    prompt_revision: str | None = None
    #: The handoff packet, present only when a person is now involved.
    handoff: str = ""
    escalation_reason: str = ""
    #: An order question from someone not signed in (ADR-0057 §7). The turn
    #: service replaces ``reply`` with the shop's sign-in sentence.
    needs_sign_in: bool = False

    @property
    def is_answer(self) -> bool:
        """Did a shopper get an actual answer, rather than a refusal or a handover?"""
        return self.state is ConversationState.RESOLVED


class AgentRunner(Protocol):
    """One agent, ready to run turns.

    ``key`` must equal the agent's manifest key: it is what the API mounts the
    routes under, what entitlements are checked against, and what usage is
    attributed to. A runner whose key disagreed with its manifest would bill one
    agent for another's work.
    """

    @property
    def key(self) -> str: ...

    async def run(self, request: TurnRequest) -> TurnOutcome: ...


#: Entry-point group. An agent registers ``<key> = "<module>:build_runner"``,
#: where ``build_runner`` takes no arguments and returns an :class:`AgentRunner`.
#: Built once per process and reused: constructing a graph per request would
#: measure graph construction as if it were latency, which is the same mistake
#: the eval target's docstring warns about.
RUNNER_ENTRY_POINT_GROUP = "neura.agent_runners"


__all__ = [
    "RUNNER_ENTRY_POINT_GROUP",
    "AgentRunner",
    "Citation",
    "Progress",
    "ProgressKind",
    "ProgressSink",
    "TurnOutcome",
    "TurnRequest",
]
