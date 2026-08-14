"""One turn, from an authenticated request to a durable record of what happened.

This module is the answer to three things milestone 1.13 left as seams, and it
is worth naming them together because they are the same mistake in three costumes
— a control that is built, tested, and called by nobody:

* **Authentication** worked and no request path invoked it. It does now, in
  ``dependencies.py``, before anything here runs.
* **Usage** (open question **P5**) — the meter, the rollup and the ladder all
  existed and no code wrote a row, so ``spend_today`` was always zero and every
  budget in ADR-0015 was untriggerable. :func:`run_turn` records a
  ``UsageDelta`` per turn, in the same transaction as the transcript.
* **The audit sink** (open question **S5**) — the graph wrote ``guard.block``
  into ``None``, which is the cheap-and-invisible outcome ADR-0012 rejected.
  A served turn gets a real one.

**The order of operations is the design.** Budget is resolved *before* the turn,
from what the tenant has already spent, and the ceilings it produces are passed
into the runtime — so a tenant over its hard limit has an empty tool allowlist
before the first model call, rather than being stopped after paying for one.
Usage is recorded *after*, because that is when the numbers exist.

**Transactions are short and there are several.** A turn takes seconds; holding
one pooled connection across all of it would let ten concurrent shoppers exhaust
a ten-connection pool. So: one transaction to read the tenant's position and open
the conversation, none at all while the models and the merchant's shop are
working, and one at the end that writes the transcript, the usage row and the
outbound events together. The audit sink opens its own, per entry, for the reason
in ``audit.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from neura_agent_core.conversations import ConversationRepository, ConversationState
from neura_agent_core.rag import DatabaseVectorStore
from neura_agent_core.rag.retrieval import Retriever
from neura_agent_core.serving import AgentRunner, ProgressSink, TurnOutcome, TurnRequest
from neura_agent_core.shadow import ShadowRepository, ShadowTurn
from neura_agent_core.tools import SessionIdentity
from neura_api.audit import TenantAuditLog
from neura_api.metering import MeteredLLM
from neura_api.stores import StoreDirectory
from neura_core import Database, get_logger, get_settings, new_id
from neura_core.ids import CONVERSATION
from neura_core.tenancy import (
    Admission,
    AuthenticatedCaller,
    RuntimePolicy,
    TurnMode,
    UsageDelta,
    UsageMeter,
    resolve_runtime_policy,
    resolve_turn_mode,
)
from neura_core.webhooks import PendingEvent, WebhookEvent, WebhookRepository

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TurnInput:
    """What the transport collected. Deliberately free of HTTP."""

    caller: AuthenticatedCaller
    agent_key: str
    message: str
    conversation_id: str | None = None
    #: What the *store* has already authenticated about the shopper. It arrives
    #: from the merchant's server on a secret key and is refused on a public one
    #: — see ``routes/chat.py``. A browser cannot be trusted to name its own
    #: customer id, and a session that could would make every order in the shop
    #: readable by anyone who guessed a number.
    customer_external_id: str | None = None
    external_ref: str | None = None
    channel: str = "web"
    locale: str = "en"
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class TurnResult:
    """The outcome, plus what the transport needs to answer with."""

    conversation_id: str
    message_id: str
    outcome: TurnOutcome
    policy: RuntimePolicy
    started_conversation: bool
    #: What happened to the reply. ``SHADOW`` means the transport must not send
    #: it — see ``reply`` below, which is the only thing a route should read.
    mode: TurnMode = TurnMode.LIVE

    @property
    def is_shadowed(self) -> bool:
        return self.mode is TurnMode.SHADOW

    @property
    def state(self) -> ConversationState:
        """What the *shopper* experienced, which is what the API reports."""
        return ConversationState.SHADOWED if self.is_shadowed else self.outcome.state

    @property
    def reply(self) -> str:
        """The text to send, which for a shadowed turn is nothing at all.

        A property rather than a rule in a route handler, deliberately. There are
        two transports and there will be more, and "remember not to send the
        reply" is the kind of instruction that holds until somebody adds a third.
        Reading ``outcome.reply`` directly is now the mistake, and it is one that
        has to be made on purpose.
        """
        return "" if self.is_shadowed else self.outcome.reply


class TurnService:
    """Runs turns. One per process — it holds the shared LLM client and the
    store directory, both of which are pools rather than per-request objects."""

    def __init__(self, db: Database, llm: object, stores: StoreDirectory) -> None:
        self._db = db
        self._llm = llm
        self._stores = stores

    async def run(
        self,
        runner: AgentRunner,
        turn: TurnInput,
        *,
        on_progress: ProgressSink | None = None,
    ) -> TurnResult:
        tenant_id = turn.caller.tenant_id
        conversation_id = turn.conversation_id or new_id(CONVERSATION)
        settings = get_settings()

        # ── Before the turn: where does this tenant stand? ────────────────────
        async with self._db.tenant_session(tenant_id) as session:
            spend = await UsageMeter(session).spend_today(tenant_id)
            conversations = ConversationRepository(session)
            started = await conversations.start(
                tenant_id,
                conversation_id=conversation_id,
                agent_key=turn.agent_key,
                external_ref=turn.external_ref,
                customer_external_id=turn.customer_external_id,
                channel=turn.channel,
                locale=turn.locale,
            )
            history = (
                []
                if started
                else await conversations.history(
                    tenant_id, conversation_id, turns=settings.conversation_history_turns
                )
            )

        # Entitlement and budget in one call, so a route cannot forget either.
        # An unconfigured tenant with no spend resolves to `allowed_tools=None`
        # and the platform tool ceiling — byte-for-byte the runtime the eval
        # harness builds, which is what makes the golden suite evidence about
        # what is served.
        policy = resolve_runtime_policy(turn.caller.tenant, turn.agent_key, spend)
        if policy.admission is not Admission.NORMAL:
            log.warning(
                "tenant_degraded",
                tenant_id=tenant_id,
                admission=policy.admission.value,
                spend_usd=str(spend),
                soft=str(policy.limits.soft),
                hard=str(policy.limits.hard),
            )

        # ── The turn ─────────────────────────────────────────────────────────
        metered = MeteredLLM(self._llm)
        store = await self._stores.connect(tenant_id)
        try:
            outcome = await runner.run(
                TurnRequest(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    message=turn.message,
                    adapter=store.adapter,
                    llm=metered,
                    capabilities=store.capabilities,
                    # The key's scopes, not the manifest's. A key issued with
                    # fewer scopes than the agent declares must be able to do
                    # less, or scoping a key would be decorative.
                    scopes=turn.caller.scopes,
                    identity=SessionIdentity(customer_external_id=turn.customer_external_id),
                    history=history,
                    retriever=self._retriever(tenant_id, metered),
                    audit=TenantAuditLog(self._db, tenant_id),
                    allowed_tools=policy.allowed_tools,
                    max_tool_calls=policy.max_tool_calls,
                    on_progress=on_progress,
                )
            )
        finally:
            # An adapter holds an HTTP client. One built per turn and abandoned
            # leaks a connection pool per shopper.
            await _close(store.adapter)

        # Shadow mode is resolved *after* the turn, because it is per-intent and
        # the intent is something the turn produces (agent-runtime.md §6). That
        # ordering is also what makes a shadow turn worth anything: the whole
        # graph has already run, on the same models with the same tools, so what
        # a human grades is the answer the shopper would have received rather
        # than a cheaper approximation of it.
        mode = resolve_turn_mode(
            tenant_mode=turn.caller.tenant.config.mode,
            shadow_intents=turn.caller.tenant.config.shadow_intents,
            intent=outcome.intent,
        )

        # ── After the turn: one transaction, everything or nothing ───────────
        async with self._db.tenant_session(tenant_id) as session:
            conversations_repo = ConversationRepository(session)

            if mode is TurnMode.SHADOW:
                # The shopper's words are history; the agent's are not. The
                # draft goes to the review queue in this same transaction, so
                # "withheld from the shopper" and "recorded for a human" cannot
                # come apart.
                message_id = await conversations_repo.append_shopper_message(
                    tenant_id,
                    conversation_id,
                    shopper=turn.message,
                    trace_id=turn.trace_id or None,
                )
                await ShadowRepository(session).record(
                    _shadow_turn(
                        outcome,
                        metered,
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        agent_key=turn.agent_key,
                        mode=mode,
                    )
                )
            else:
                _, message_id = await conversations_repo.append_turn(
                    tenant_id,
                    conversation_id,
                    # As the guard left it. A transcript kept under a merchant's
                    # retention policy must not become a long-term store of card
                    # numbers (security-model.md §6.2) — the rehydrated text exists
                    # only in the reply the shopper saw.
                    shopper=turn.message,
                    reply=outcome.reply,
                    state=outcome.state,
                    intent=outcome.intent,
                    citations=[c.as_dict() for c in outcome.citations],
                    trace_id=turn.trace_id or None,
                    prompt_revision=outcome.prompt_revision,
                )

            await UsageMeter(session).record(
                tenant_id,
                turn.agent_key,
                _delta(outcome, metered, conversation_started=started),
            )

            # The ladder rung this turn *ended* on. Compared against the rung
            # it started on so `budget.threshold.reached` fires on the
            # crossing and not on every turn for the rest of the day — a
            # webhook per message is the interruption ADR-0012 rejected,
            # arriving through a different door.
            crossed_into = policy.limits.admit(spend + metered.spend.cost_usd)

            await _emit(
                session,
                tenant_id,
                conversation_id=conversation_id,
                outcome=outcome,
                mode=mode,
                policy=policy,
                spend=spend + metered.spend.cost_usd,
                crossed_into=crossed_into,
                started=started,
            )

        log.info(
            "turn_completed",
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            agent=turn.agent_key,
            state=outcome.state.value,
            tool_calls=outcome.tool_calls,
            llm_calls=metered.spend.calls,
            cost_usd=str(metered.spend.cost_usd),
            admission=policy.admission.value,
            mode=mode.value,
        )

        return TurnResult(
            conversation_id=conversation_id,
            message_id=message_id,
            outcome=outcome,
            policy=policy,
            started_conversation=started,
            mode=mode,
        )

    def _retriever(self, tenant_id: str, llm: object) -> Retriever | None:
        """Retrieval over the tenant's indexed catalogue and policy pages.

        The metered client is passed in deliberately: an embedding call for a
        shopper's query is a real cost, and a meter that counted the reasoner
        but not the embedder would under-report the cheap calls that happen on
        every single turn.
        """
        return Retriever(DatabaseVectorStore(self._db, tenant_id), llm, tenant_id=tenant_id)  # type: ignore[arg-type]


def _delta(outcome: TurnOutcome, metered: MeteredLLM, *, conversation_started: bool) -> UsageDelta:
    """One turn's consumption, exactly as open question P5 specifies it.

    *Turns, LLM calls and ``cost_usd`` from the client; tool calls and
    escalations from the graph.* Neither side invents the other's numbers, which
    is why ``UsageDelta`` defaults every counter to zero.

    A turn the provider was never reachable for still counts as a turn and costs
    nothing, which is correct on both halves: the merchant used the service, and
    the models were not called.
    """
    spend = metered.spend
    return UsageDelta(
        conversations=1 if conversation_started else 0,
        turns=1,
        llm_calls=spend.calls,
        tool_calls=outcome.tool_calls,
        escalations=1 if outcome.escalated else 0,
        blocked=1 if outcome.blocked else 0,
        prompt_tokens=spend.prompt_tokens,
        completion_tokens=spend.completion_tokens,
        cost_usd=spend.cost_usd,
    )


def _shadow_turn(
    outcome: TurnOutcome,
    metered: MeteredLLM,
    *,
    tenant_id: str,
    conversation_id: str,
    message_id: str,
    agent_key: str,
    mode: TurnMode,
) -> ShadowTurn:
    """One withheld turn, as a human will read it weeks later.

    ``draft`` rather than ``reply`` — tokenised, and present even when the turn
    escalated, which is the case somebody most wants to read. What the reply
    *would* have been is the whole artefact here; ``outcome.reply`` is empty on an
    escalated turn and rehydrated on an answered one, and neither is what belongs
    in a queue kept for six weeks.

    The cost figures come from the meter and the graph separately, exactly as the
    usage row does (open question P5): neither side invents the other's numbers.
    """
    return ShadowTurn(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
        agent_key=agent_key,
        mode=mode.value,
        # The outcome the *agent* reached, not the one the shopper experienced.
        # `TurnResult.state` reports the second; this records the first, and a
        # scorecard that could not tell them apart would be measuring the mode.
        state=outcome.state.value,
        draft=outcome.draft or outcome.reply,
        intent=outcome.intent,
        escalated=outcome.escalated,
        grounded=outcome.grounded,
        verify_reason=outcome.verify_reason,
        tools=[c.id for c in outcome.citations if c.type == "tool"],
        citations=[c.as_dict() for c in outcome.citations],
        tool_calls=outcome.tool_calls,
        llm_calls=metered.spend.calls,
        cost_usd=metered.spend.cost_usd,
    )


async def _emit(
    session: object,
    tenant_id: str,
    *,
    conversation_id: str,
    outcome: TurnOutcome,
    mode: TurnMode,
    policy: RuntimePolicy,
    spend: Decimal,
    crossed_into: Admission,
    started: bool,
) -> None:
    """Queue the outbound events this turn earned.

    In the transaction that wrote the turn, so an event exists exactly when the
    thing it describes happened. A tenant with no registered endpoints costs one
    indexed read and writes nothing.

    **A blocked turn emits no event.** ADR-0012's whole argument for blocking
    rather than escalating is that the merchant learns *in aggregate* rather
    than by interruption, and a webhook per blocked message is an interruption
    with extra steps. The count is in ``tenant_usage.blocked`` and the named
    event is in the audit log.
    """
    repository = WebhookRepository(session)  # type: ignore[arg-type]
    events: list[PendingEvent] = []

    if started:
        events.append(
            PendingEvent(
                event=WebhookEvent.CONVERSATION_STARTED,
                conversation_id=conversation_id,
                payload={"conversation_id": conversation_id},
            )
        )

    # **A shadowed turn emits neither outcome event, and the reason is the same
    # one that makes the state a fifth value rather than a flag.** Nobody was
    # escalated to and nothing was resolved: the reply was never sent. A
    # `conversation.escalated` webhook here would put a ticket in a merchant's
    # queue for a handover that did not happen, which is worse than silence
    # because it is actionable. `conversation.started` above still fires — the
    # conversation genuinely started — and so do the budget events below, because
    # a shadow turn spends real money.
    if mode is TurnMode.SHADOW:
        pass
    elif outcome.escalated:
        events.append(
            PendingEvent(
                event=WebhookEvent.CONVERSATION_ESCALATED,
                conversation_id=conversation_id,
                payload={
                    "conversation_id": conversation_id,
                    "reason": outcome.escalation_reason,
                    # The handoff packet, which is the whole point of the event:
                    # a merchant receiving "escalated" with no context has to go
                    # and look it up before they can act on it. It is rehydrated
                    # (escalate.py), because the recipient is the customer's own
                    # merchant and a puzzle is not a ticket.
                    "handoff": outcome.handoff,
                },
            )
        )
    elif outcome.state is ConversationState.RESOLVED:
        events.append(
            PendingEvent(
                event=WebhookEvent.CONVERSATION_RESOLVED,
                conversation_id=conversation_id,
                payload={"conversation_id": conversation_id, "intent": outcome.intent},
            )
        )

    if crossed_into is not policy.admission:
        events.append(
            PendingEvent(
                event=WebhookEvent.BUDGET_THRESHOLD_REACHED,
                payload={
                    "admission": crossed_into.value,
                    "previous_admission": policy.admission.value,
                    "spend_usd": str(spend),
                    "soft_limit_usd": str(policy.limits.soft),
                    "hard_limit_usd": str(policy.limits.hard),
                },
            )
        )

    for event in events:
        await repository.enqueue(tenant_id, event)


async def _close(adapter: object) -> None:
    closer = getattr(adapter, "aclose", None)
    if closer is not None:
        await closer()


__all__ = ["TurnInput", "TurnResult", "TurnService"]
