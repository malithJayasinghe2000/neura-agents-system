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
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig

from neura_agent_core.guard.pii import PiiVault
from neura_agent_core.policy.engine import ConversationBudget, Decision, PolicyEngine
from neura_agent_core.rag.retrieval import Retriever
from neura_agent_core.tools.executor import ToolInvocation
from neura_agent_core.tools.registry import ToolRegistry
from neura_agent_core.tools.spec import ToolContext

if TYPE_CHECKING:
    # Type-only, and it has to stay that way. `neura_agent_core.audit` reads the
    # `audit_log` table definition out of `graph.schema`, so importing it here at
    # runtime closes a cycle — audit → graph.schema → graph/__init__ → nodes →
    # state → audit — and whether it fires depends on which module a process
    # happens to import first. The unit suite imported `audit` late and was fine;
    # the integration suite imported it first and could not collect.
    from neura_agent_core.audit import AuditSink

#: Set to a falsey string to disable the guard's rules for a measurement run.
GUARD_ENV_VAR = "NEURA_GUARD_ENABLED"

_FALSEY = frozenset({"0", "false", "no", "off"})


#: Exception type names meaning **the model did not answer**, as opposed to the
#: model answering with something unusable.
#:
#: ``ProviderRateLimitedError`` joined this set on 2026-09-06 ([ADR-0036]) and it
#: is the sharper half of open question E9. It is a *sibling* of the other two
#: under `LLMError`, not a subclass, so a quota exhaustion used to be scored as
#: agent behaviour — and on 2026-09-06 it was: the OpenRouter free tier refused
#: all 47 guard-off cases, every turn escalated without proposing a tool, and the
#: report printed **injection resistance 1.00 ✔**. A turn that never reached a
#: model cannot propose an unauthorised call, so the project's one
#: release-blocking gate was satisfied by a rate limiter — AGENTS.md's own stated
#: failure mode for that command, with a quota standing where the guard stands.
#:
#: A refusal for quota is not "unreachable" in the network sense, and the name of
#: this function is now slightly generous. What the set actually means is *the
#: provider produced no answer*, and every member is a reason to stop measuring.
PROVIDER_DID_NOT_ANSWER = frozenset(
    {"ProviderUnavailableError", "ProviderTimeoutError", "ProviderRateLimitedError"}
)


def unreachable_provider(exc: BaseException) -> bool:
    """Did this exception mean "the model did not answer", rather than "the model
    said something unusable"?

    Matched on the exception *type name* rather than by importing
    ``neura_llm.ProviderUnavailableError``, deliberately: this module is imported
    by every graph, and a node that stubs its LLM in a test must not have to
    install a provider package to say so. The name is stable and the failure of
    this check is safe in the honest direction — an unrecognised exception is
    scored as an agent decision, which is what happens today.
    """
    return any(cls.__name__ in PROVIDER_DID_NOT_ANSWER for cls in type(exc).__mro__)


def guard_enabled_by_default() -> bool:
    """Read the guard flag from the environment, defaulting to on.

    Read here rather than from :func:`neura_core.get_settings` on purpose. That
    function is ``lru_cache``d for the process lifetime, which is right for a
    database URL and wrong for a flag whose entire job is to be flipped between
    two runs of the same suite — a cached value would make
    ``make eval-guard-off`` silently measure the same thing twice.
    """
    return os.environ.get(GUARD_ENV_VAR, "true").strip().lower() not in _FALSEY


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

    #: The names of the rules that matched, comma-joined — never the text that
    #: matched them. This value is checkpointed and logged, and an attack message
    #: quoted into either is an attack message kept for as long as the row lives.
    block_reason: str

    #: The tokens `guard` issued for this turn — `["[EMAIL_1]", "[PHONE_1]"]`.
    #:
    #: **Token names only, and that is the point.** The mapping back to real
    #: values lives on :class:`Runtime`, which is per-turn and never
    #: checkpointed, so a conversation resumed from Postgres tomorrow cannot
    #: re-expose what was tokenised today (security-model.md §6.2). What is safe
    #: to persist is the fact that an email was present, not whose.
    redactions: list[str]

    #: Personal data found in the finished reply that nothing in the turn
    #: accounts for (security-model.md §6.3, threat T10). Non-empty means the
    #: turn escalated instead of answering. Descriptions, never values.
    pii_leaks: list[str]

    #: Set when a node could not reach the model provider at all — Ollama down,
    #: a cloud API refusing, a network partition.
    #:
    #: **This is not an agent decision and must never be scored as one.** The
    #: graph degrades correctly when a provider vanishes: `route` cannot classify,
    #: so it escalates, which is the right thing to do and is indistinguishable
    #: from an honest "I am not sure" — until you notice that *every* case did it.
    #: Measured on 2026-07-31: Ollama died mid-run and the suite reported intent
    #: accuracy 0.00 and tool selection 0.00, which reads as a total agent
    #: collapse and was a dead server.
    #:
    #: The eval harness reads this and **skips** those cases rather than failing
    #: them, for the same reason an unreachable judge is skipped rather than
    #: scored as a hallucination (open question E6, and the general lesson of
    #: 1.11: "not measured" has to be its own value).
    infrastructure_error: str

    #: Commitments in the draft that the agent cannot honour — "I'll send you a
    #: prepaid label" in a system with no later turn and no WRITE tool (open
    #: question A9(3)). Non-empty means the turn escalated. Descriptions, never
    #: the sentence: the handoff already carries the draft in full.
    promises: list[str]

    #: Why a turn ended with nothing to offer, when that is an *answer* rather
    #: than a failure. Set by the node that decided it; read by the node that
    #: writes the fixed reply. See [ADR-0027].
    #:
    #: ``kind`` is the situation and the rest are its facts, all strings so the
    #: value checkpoints cleanly:
    #:
    #: * ``{"kind": "empty"}`` — the catalogue was searched and returned nothing.
    #: * ``{"kind": "constraint", "found": "4", "ceiling": "40.00",
    #:   "cheapest": "44.00", "currency": "USD"}`` — products came back and the
    #:   shopper's own stated limit excluded every one of them.
    #:
    #: **Facts, never a sentence.** The wording lives in a prompt file and the
    #: numbers are copied from tool output, which is what keeps the reply a
    #: template rather than a generation — no model writes this, so there is no
    #: ungrounded claim for `verify` to catch.
    #:
    #: Deliberately not named for one agent: "there is nothing to offer, and
    #: here is precisely why" is a shape any agent can reach.
    miss: dict[str, str]

    #: Structured items the reply may *display*, in the order it names them.
    #: See [ADR-0030]. Fields only — a title, a price, a link — never markup.
    #:
    #: Declared here because **an undeclared key is dropped silently by
    #: LangGraph**, and a card list that vanishes between `respond` and the API
    #: would look exactly like a turn that recommended nothing.
    cards: list[dict[str, str]]

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

    #: An order question from someone not signed in (ADR-0057 §7). Not a
    #: handover: the turn ends asking the shopper to sign in, and the turn
    #: service puts on the shop's words.
    needs_sign_in: bool

    #: The agent answered by declining — the question was outside its scope and
    #: no person was needed. Distinct from ``escalated``, and the distinction is
    #: the point: both end the turn without an answer, but only one occupies a
    #: human. Conflating them makes escalation *precision* unreadable, since
    #: every off-topic question would count against it.
    refused: bool

    #: Cost and latency, accumulated for the budget and the merchant's bill.
    usage: dict[str, Any]


def infra_error(exc: BaseException, detail: str) -> AgentState:
    """State to merge when a node's failure was the provider, not the agent.

    Returns an **empty** update for any other exception, so every call site can
    splat it unconditionally:

        return {**_escalate("routing could not be completed"), **infra_error(exc, "…")}

    Empty-on-no-match is the safe direction. A failure we do not recognise stays
    scored as an agent decision, which is exactly what happens today — the fix
    can only ever *remove* a false measurement, never invent a skip.
    """
    if not unreachable_provider(exc):
        return {}
    return cast("AgentState", {"infrastructure_error": f"{detail}: {type(exc).__name__}"})


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

    #: This turn's PII redaction map. Deliberately here and not in the state:
    #: the state is checkpointed to PostgreSQL after every node, and a token map
    #: written to a database is a token map that outlives the session it was
    #: meant to last for (security-model.md §6.2). `guard` fills it, `respond`
    #: and `escalate` read it, and it dies with the turn.
    vault: PiiVault = field(default_factory=PiiVault)

    #: Structured facts a tool saw this turn, keyed by id, for a reply that has
    #: to *show* something rather than only describe it. See [ADR-0030].
    #:
    #: Here for the same reason `vault` is: it is per-turn, it is never
    #: checkpointed, and the objects a tool fetched have no business in a
    #: database row. The same dict is handed to :class:`ToolContext`, so a tool
    #: writes and a terminal node reads without either learning about the other.
    #:
    #: Agent-neutral by construction — the engine never learns what an entry
    #: means, only that a node asked for one by id.
    cards: dict[str, dict[str, str]] = field(default_factory=dict)

    #: Whether `guard`'s rules run at all. Off is a *measurement* mode, not a
    #: deployment mode — `make eval-guard-off` uses it to prove that injection
    #: resistance comes from the policy engine and not from the guard (ADR-0011).
    #: The node logs a warning on every turn when it is off, because a disabled
    #: control that says nothing looks exactly like an enabled one.
    guard_enabled: bool = field(default_factory=lambda: guard_enabled_by_default())

    #: Where security events go. Optional for the same reason `retriever` is:
    #: a graph must be runnable in a unit test without a database. **A block
    #: with no sink is a block nobody can count**, which is most of what makes
    #: blocking defensible instead of merely cheap (ADR-0012) — so the serving
    #: path must wire a real one.
    audit: AuditSink | None = None
    #: The LLM client. Typed loosely so `neura-agent-core` does not force a
    #: particular client on an agent that stubs it in tests.
    llm: Any = None
    #: Narrows the evidence `verify` asks the model about, given ``(draft,
    #: evidence)`` and returning the text to check claims against.
    #: ``None`` — the default — hands over the evidence unchanged, which is what
    #: CARE does and what every agent did before ADR-0025.
    #:
    #: **The seam is here rather than in the node because a product id is not a
    #: concept this package has.** `neura-agent-core` supplies the machinery and
    #: never learns which product it is running; SELL supplies a callable because
    #: SELL is the agent whose evidence is a catalogue.
    #:
    #: **It narrows what the verifier is *asked*, and nothing else.** The
    #: outbound PII check still accounts against the full evidence, and so does
    #: the empty-evidence test — see `nodes/verify.py`, where mixing the two up
    #: turns a filter into a bypass.
    evidence_filter: Callable[[str, str], str] | None = None

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
        redactions=[],
        pii_leaks=[],
        promises=[],
        usage={},
    )
