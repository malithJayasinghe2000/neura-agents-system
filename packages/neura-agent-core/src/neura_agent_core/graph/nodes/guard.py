"""The ``guard`` node — the first thing a shopper's message meets.

`agent-runtime.md §2` gives it two jobs, and it does exactly those two and
nothing else:

1. **Scan the untrusted text for a recognisable attack.** A hit ends the turn at
   `blocked` — a canned reply and a security event, costing the merchant a log
   line instead of a person (ADR-0012).
2. **Redact personal data before any model sees it**, reversibly, with the
   mapping held for the turn in :class:`~neura_agent_core.guard.pii.PiiVault`
   (security-model.md §6.1). `respond` puts it back.

**Nothing here is a security boundary, and the wording matters.** Injection
resistance was 1.00 before this node existed, because there is no WRITE tool to
invoke and every call is authorised in code (security-model.md §2.1). This node
cannot raise that number and must never be credited with it — which is why it can
be switched off, and why the suite is run with it off. If `make eval-guard-off`
ever drops below 1.00, the thing that broke is the structural defence, and no
amount of rule-writing here is the fix.

**It is also why the node is deterministic.** A classifier here would need a
threshold, there is no labelled corpus to tune one against (open question S1),
and a classifier reading the attacker's text is itself a thing the attacker is
writing to. ADR-0011 has the argument; the rules are in
:mod:`neura_agent_core.guard.injection`.

## The order of operations, which is load-bearing

Redaction happens **after** the attack scan and **before** anything is recorded.
The scan runs on the original text because no rule depends on an email address,
and reading the original keeps the rules simple. The audit entry and every log
line then carry the *redacted* message, so a two-year audit log does not become
the place a shopper's card number is kept.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph.state import AgentState, Runtime, runtime_of
from neura_agent_core.guard.injection import scan
from neura_core import get_logger

log = get_logger(__name__)

ACTOR = "guard"


async def guard(state: AgentState, config: RunnableConfig) -> AgentState:
    """Scan, redact, and either block the turn or let it through."""
    runtime = runtime_of(config or {})
    message = state.get("message", "")

    if not runtime.guard_enabled:
        # Logged at WARNING on every turn, on purpose. A disabled security
        # control that says nothing is indistinguishable from an enabled one,
        # and this flag exists to be *measured* with (`make eval-guard-off`),
        # not to be left off.
        log.warning(
            "guard_disabled",
            conversation_id=state.get("conversation_id"),
            tenant_id=state.get("tenant_id"),
        )
        return {"blocked": False, "redactions": []}

    verdict = scan(message)

    if verdict.is_attack:
        return await _block(runtime, state, verdict.rules)

    # Redact the shopper's message and every previous turn. History matters as
    # much as the message: an email typed three turns ago is still in the
    # context window this turn puts in front of a model.
    redacted_message = runtime.vault.redact(message)
    redacted_history = [
        {**turn, "content": runtime.vault.redact(turn.get("content", ""))}
        for turn in state.get("history", [])
    ]

    if len(runtime.vault):
        log.info(
            "pii_redacted",
            conversation_id=state.get("conversation_id"),
            tenant_id=state.get("tenant_id"),
            # Token names only. `[EMAIL_1]` says an email was present without
            # saying whose, which is the whole point of the exercise.
            tokens=runtime.vault.tokens,
        )

    return {
        "blocked": False,
        "message": redacted_message,
        "history": redacted_history,
        "redactions": runtime.vault.tokens,
    }


async def _block(runtime: Runtime, state: AgentState, rules: tuple[str, ...]) -> AgentState:
    """End the turn, and make sure somebody could find out that it happened.

    The security event is what makes blocking defensible rather than merely
    cheap. A block that nobody can see is the objection that was raised against
    silently declining (open question A5) and it applies here with more force:
    "we are being probed" is information a merchant is entitled to, and a
    per-message handover is the wrong way to deliver it. Aggregate, not
    interrupt (security-model.md §2.2, layer 7).
    """
    # Imported here, not at module scope. `neura_agent_core.audit` reads the
    # `audit_log` table out of `graph.schema`, which pulls in `graph/__init__`,
    # which pulls in this module — a cycle that fires or does not depending on
    # which module a process imports first. Deferring it to the one code path
    # that needs it keeps the graph package importable from either direction.
    from neura_agent_core.audit import AuditEntry, AuditEvent

    reason = ", ".join(rules)

    # Redacted before it is recorded anywhere. The audit log is kept for two
    # years (§6.2); an attack message containing a real card number would
    # otherwise be retained far longer than the card data it quotes.
    redacted = runtime.vault.redact(state.get("message", ""))

    log.warning(
        "guard_blocked",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
        rules=list(rules),
    )

    if runtime.audit is not None:
        await runtime.audit.record(
            AuditEntry(
                tenant_id=state.get("tenant_id", ""),
                event_type=AuditEvent.GUARD_BLOCK,
                actor=ACTOR,
                outcome=reason,
                conversation_id=state.get("conversation_id"),
                payload={"rules": list(rules), "message": redacted},
            )
        )

    return {
        "blocked": True,
        "block_reason": reason,
        "message": redacted,
        "redactions": runtime.vault.tokens,
    }
