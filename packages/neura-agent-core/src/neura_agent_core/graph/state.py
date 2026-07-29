"""What a conversation turn carries between nodes.

The state *is* the explanation. ADR-0004 chose an explicit graph over an agent
loop mainly so that "why did it say that?" has an answer, and this is where the
answer accumulates: what the router decided, what was retrieved, which tools
were authorised and which were refused, what was drafted, and whether verify
accepted it.

Two rules about what may live here:

* **Only serialisable data.** The state is checkpointed to PostgreSQL after
  every node, so a worker restart resumes a conversation mid-turn. A live
  adapter or an HTTP client cannot be checkpointed, so runtime dependencies
  travel in :class:`Runtime` via the graph's config instead.
* **Append, don't overwrite, anything that is evidence.** Tool invocations and
  policy decisions use additive reducers: a later node cannot erase the record
  of an earlier refusal, which is what makes the audit trail trustworthy.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig

from neura_agent_core.policy.engine import ConversationBudget, Decision, PolicyEngine
from neura_agent_core.rag.retrieval import Retriever
from neura_agent_core.tools.executor import ToolInvocation
from neura_agent_core.tools.registry import ToolRegistry
from neura_agent_core.tools.spec import ToolContext


class AgentState(TypedDict, total=False):
    """One turn, from the shopper's message to the reply or the escalation."""

    # ── Input ────────────────────────────────────────────────────────────────
    tenant_id: str
    conversation_id: str
    message: str

    #: Previous turns, oldest first, each ``{"role": ..., "content": ...}``.
    #: Supplied by whatever starts the turn — an API request, an eval case.
    #:
    #: This is the *seam*, not a memory tier. The Redis session store and the
    #: Postgres transcript of memory §4 do not exist yet; when they do, they fill
    #: this key and nothing in any graph changes. Declared here because a node
    #: cannot resolve "what colours does it come in?" without the turn that said
    #: which product, and an undeclared key is dropped silently by LangGraph.
    history: list[dict[str, str]]

    # ── guard ────────────────────────────────────────────────────────────────
    blocked: bool
    block_reason: str

    # ── route ────────────────────────────────────────────────────────────────
    intent: str
    intent_confidence: float
    entities: dict[str, str]

    #: A **self-contained** restatement of what the shopper is asking, written by
    #: the agent's routing step and used by `retrieve` in place of the raw
    #: message.
    #:
    #: This exists because of a finding from milestone 1.9: "what colours does it
    #: come in?" retrieved the Payment Policy at 0.502, because "it" has no
    #: referent once the sentence leaves the conversation. Retrieval cannot fix
    #: that — the pronoun must be resolved against the history *before* anything
    #: is embedded. Optional: an agent that does not rewrite queries leaves this
    #: unset and `retrieve` falls back to the message, as it always did.
    search_query: str

    # ── retrieve ─────────────────────────────────────────────────────────────
    #: Already wrapped in `<untrusted>` delimiters, ready for a prompt.
    context: str
    sources: list[str]
    retrieval_note: str

    # ── act ──────────────────────────────────────────────────────────────────
    #: Tool calls awaiting authorisation: written by the agent's reasoning node,
    #: read by `act`. An inbox, not evidence — it is overwritten each time,
    #: unlike the two accumulators below.
    #:
    #: Declared here rather than set ad hoc, because LangGraph only propagates
    #: keys the state declares. An undeclared key is dropped silently between
    #: nodes, and the symptom is an agent that calmly never calls any tool.
    proposed_calls: list[dict[str, Any]]

    #: Evidence. Additive on purpose — a later node must not be able to erase a
    #: record of what was refused.
    invocations: Annotated[list[ToolInvocation], operator.add]
    decisions: Annotated[list[Decision], operator.add]

    # ── compose / verify ─────────────────────────────────────────────────────
    draft: str
    grounded: bool
    verify_reason: str

    # ── outcome ──────────────────────────────────────────────────────────────
    reply: str
    escalated: bool
    escalation_reason: str
    handoff: str

    #: The agent answered by declining — the question was outside its scope and
    #: no person was needed. Distinct from ``escalated``, and the distinction is
    #: the point: both end the turn without an answer, but only one occupies a
    #: human. Conflating them makes escalation *precision* unreadable, since
    #: every off-topic question would count against it.
    refused: bool

    #: Cost and latency, accumulated for the budget and the merchant's bill.
    usage: dict[str, Any]


@dataclass(slots=True)
class Runtime:
    """Everything a node needs that cannot be checkpointed.

    Travels in the graph's ``config["configurable"]`` rather than in the state,
    for a boring but absolute reason: an HTTP client does not survive being
    written to a database and read back.

    It is also the seam that keeps ``neura-agent-core`` free of any agent's
    name. An agent supplies its own prompts, intents and tools; the engine
    supplies the machinery and never learns which product it is running.
    """

    ctx: ToolContext
    registry: ToolRegistry
    policy: PolicyEngine
    budget: ConversationBudget = field(default_factory=ConversationBudget)
    #: Optional: an agent that answers only from tools needs no retrieval.
    retriever: Retriever | None = None
    #: The LLM client. Typed loosely so `neura-agent-core` does not force a
    #: particular client on an agent that stubs it in tests.
    llm: Any = None
    #: Per-node prompt text, supplied by the agent. Never inline strings here —
    #: prompts are versioned files in the agent's `prompts/` (AGENTS.md).
    prompts: dict[str, str] = field(default_factory=dict)

    def prompt(self, name: str) -> str:
        """Fail loudly on a missing prompt.

        A node silently running with an empty system prompt still produces
        fluent text — it simply stops following any of its instructions, which
        is the kind of failure that gets discovered in a transcript weeks later.
        """
        text = self.prompts.get(name)
        if not text:
            raise KeyError(
                f"no prompt named {name!r} was supplied to the runtime; "
                f"available: {sorted(self.prompts)}"
            )
        return text


CONFIG_KEY = "neura_runtime"


#: Annotated ``RunnableConfig`` exactly, with no ``| None`` and no default.
#: LangGraph decides whether to inject the config by comparing this annotation
#: against a fixed set, and because this package uses postponed annotation
#: evaluation the comparison is against the *string* "RunnableConfig". The union
#: form is not in that set, so writing `RunnableConfig | None` here silently
#: stops the config being passed — the node then runs with no runtime at all.
#: LangGraph warns about it; the warning is easy to miss, the failure is not.
def runtime_of(config: RunnableConfig | dict[str, Any] | None) -> Runtime:
    """Pull the runtime out of a LangGraph config."""
    runtime = dict(config or {}).get("configurable", {}).get(CONFIG_KEY)
    if not isinstance(runtime, Runtime):
        raise RuntimeError(
            "the graph was invoked without a Runtime; pass "
            f'config={{"configurable": {{"{CONFIG_KEY}": runtime}}}}'
        )
    return runtime


def initial_state(
    *,
    tenant_id: str,
    conversation_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> AgentState:
    """A turn's starting state, with every accumulator empty.

    Defaults matter here: ``escalated`` and ``blocked`` start ``False``, and
    ``grounded`` is deliberately absent rather than ``True`` — "not yet checked"
    and "checked and fine" must not be the same value.
    """
    return AgentState(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message=message,
        history=list(history or []),
        blocked=False,
        escalated=False,
        invocations=[],
        decisions=[],
        entities={},
        sources=[],
        usage={},
    )
