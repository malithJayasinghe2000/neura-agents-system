"""Assembling an agent's graph, with the guarantees that make it safe.

ADR-0004 chose an explicit graph over an agent loop so that ``guard`` and
``verify`` are *structural steps*, not instructions a model can be talked past.
That is only true if a graph cannot be built without them — otherwise the
guarantee is a convention, and conventions are what a rushed afternoon breaks.

So this builder is not a thin wrapper over ``StateGraph``. It refuses to compile
a graph that:

* can reach ``respond`` without passing through ``verify`` — an unverified
  answer is the confident-wrong-answer failure the whole design is arranged
  against;
* has no ``escalate`` — an agent with no way out must answer everything, and
  answering everything is worse than knowing its limits;
* wires ``guard`` anywhere but first — a guard that runs after routing has
  already handed the attacker's text to a model, and has already let a shopper's
  card number past the point where redaction was supposed to happen;
* lets ``blocked`` fall through into the answering path — a blocked turn that
  continues is a block in name only.

**This package never learns an agent's name.** The builder takes nodes and edges
from the agent; ``neura-agent-core`` supplies ``retrieve``, ``act``, ``verify``
and ``escalate`` and has no idea whether it is running CARE or anything else
(overview.md §4.1).
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any

from langgraph.graph import END, START, StateGraph

from neura_agent_core.graph.nodes.act import act
from neura_agent_core.graph.nodes.blocked import blocked
from neura_agent_core.graph.nodes.escalate import escalate
from neura_agent_core.graph.nodes.guard import guard
from neura_agent_core.graph.nodes.retrieve import retrieve
from neura_agent_core.graph.nodes.verify import verify
from neura_agent_core.graph.state import AgentState
from neura_core import get_logger

log = get_logger(__name__)

RESPOND = "respond"
VERIFY = "verify"
ESCALATE = "escalate"
GUARD = "guard"
BLOCKED = "blocked"

#: The nodes every agent inherits. An agent may override any of them by
#: registering its own under the same name — but it starts with these, so
#: "we forgot to add verify" is not a thing that can happen by omission.
#:
#: Registered is not the same as *reachable*: a node nothing routes to never
#: runs. ``guard`` and ``blocked`` are opt-in in exactly that sense, and the
#: contract below is what makes opting in safe rather than approximate.
SHARED_NODES: dict[str, Callable[..., Any]] = {
    "retrieve": retrieve,
    "act": act,
    VERIFY: verify,
    ESCALATE: escalate,
    GUARD: guard,
    BLOCKED: blocked,
}


class GraphContractError(Exception):
    """A graph was assembled that cannot be safe. Raised at build time."""


class AgentGraph:
    """Builds one agent's state machine.

    Usage is deliberately explicit — every node and every edge is named by the
    agent, because "why did it say that?" is answered by reading the graph.
    """

    def __init__(self) -> None:
        self._graph: StateGraph[AgentState] = StateGraph(AgentState)
        self._nodes: dict[str, Callable[..., Any]] = {}
        self._edges: set[tuple[str, str]] = set()
        self._conditional: dict[str, set[str]] = {}
        self._entry: str | None = None

        for name, fn in SHARED_NODES.items():
            self.node(name, fn)

    def node(self, name: str, fn: Callable[..., Any]) -> AgentGraph:
        """Add or replace a node."""
        self._nodes[name] = fn
        return self

    def entry(self, name: str) -> AgentGraph:
        self._entry = name
        return self

    def edge(self, source: str, target: str) -> AgentGraph:
        self._edges.add((source, target))
        return self

    def branch(
        self, source: str, chooser: Callable[..., str], targets: dict[Hashable, str]
    ) -> AgentGraph:
        """A conditional edge. ``targets`` maps the chooser's return to a node."""
        self._conditional.setdefault(source, set()).update(targets.values())
        self._graph.add_conditional_edges(source, chooser, targets)
        return self

    def compile(self, checkpointer: Any = None) -> Any:
        """Check the contract, then hand back a runnable graph."""
        self._check_contract()

        for name, fn in self._nodes.items():
            self._graph.add_node(name, fn)

        if self._entry is None:
            raise GraphContractError("no entry node — call .entry(name)")
        self._graph.add_edge(START, self._entry)

        for source, target in self._edges:
            self._graph.add_edge(source, END if target == END else target)

        log.info("graph_compiled", nodes=sorted(self._nodes), entry=self._entry)
        return self._graph.compile(checkpointer=checkpointer)

    # ── The contract ─────────────────────────────────────────────────────────

    def _check_contract(self) -> None:
        if ESCALATE not in self._nodes:
            raise GraphContractError(
                "a graph must have an `escalate` node. An agent with no way to hand "
                "over must answer everything, and an agent that answers everything is "
                "worse than one that knows its limits (agent-runtime.md §5)."
            )

        if RESPOND in self._nodes:
            self._require_verified_before_respond()

        self._require_guard_first()
        self._require_blocked_terminal()

    def _require_guard_first(self) -> None:
        """If ``guard`` runs at all, it runs before anything else.

        ``guard`` does two things that are only worth doing first: it scans the
        shopper's text for a recognisable attack, and it replaces personal data
        with tokens *before any model sees it* (security-model.md §6.1). A guard
        wired after ``route`` has already sent the raw message to the router, so
        the redaction it performs is redaction of something already disclosed —
        and it looks exactly like a guard that works.

        Checked by reachability rather than by "is it registered", because every
        agent inherits the node whether or not it wires it up. An agent that
        never routes to ``guard`` is opting out, which is allowed and visible.
        """
        reachable = self._reachable_without(barrier=None)
        if GUARD in reachable and self._entry != GUARD:
            raise GraphContractError(
                f"`guard` is reachable but the entry node is {self._entry!r}. "
                "The guard redacts personal data before any model call and scans "
                "untrusted text before it is routed — both are worthless once "
                "another node has already read the message. Make `guard` the entry, "
                "or do not route to it at all (ADR-0011)."
            )

    def _require_blocked_terminal(self) -> None:
        """``blocked`` ends the turn. It does not lead anywhere.

        The failure this prevents is not a direct edge somebody would notice —
        it is a later refactor that gives every terminal node a common exit for
        logging, and quietly turns a refusal into a detour.
        """
        outgoing = {target for source, target in self._edges if source == BLOCKED}
        outgoing |= self._conditional.get(BLOCKED, set())
        outgoing.discard(END)

        if outgoing:
            raise GraphContractError(
                f"`blocked` has outgoing edges to {sorted(outgoing)}. A blocked turn "
                "must end: it is a refusal with no answer, no handoff and no tool call, "
                "and anything downstream of it is a way for the refusal not to happen "
                "(ADR-0012)."
            )

    def _require_verified_before_respond(self) -> None:
        """No path may reach ``respond`` without passing ``verify``.

        Walked from the entry node rather than checked locally, because the
        dangerous version of this bug is not a direct ``compose → respond``
        edge that anyone would notice in review — it is a detour added months
        later that happens to route around the check.
        """
        reachable_unverified = self._reachable_without(VERIFY)
        if RESPOND in reachable_unverified:
            raise GraphContractError(
                "`respond` is reachable without passing through `verify`. An "
                "unverified answer about someone's order or money is the failure "
                "this design exists to prevent — route the path through `verify`, "
                "or escalate (ADR-0004)."
            )

    def _reachable_without(self, barrier: str | None) -> set[str]:
        """Every node reachable from the entry without crossing ``barrier``.

        ``barrier=None`` means "no barrier" — plain reachability, which is what
        the guard contract needs.
        """
        adjacency: dict[str, set[str]] = {}
        for source, target in self._edges:
            adjacency.setdefault(source, set()).add(target)
        for source, targets in self._conditional.items():
            adjacency.setdefault(source, set()).update(targets)

        seen: set[str] = set()
        frontier = [self._entry] if self._entry else []

        while frontier:
            current = frontier.pop()
            if current in seen or current == barrier:
                continue
            seen.add(current)
            frontier.extend(adjacency.get(current, ()))

        return seen
