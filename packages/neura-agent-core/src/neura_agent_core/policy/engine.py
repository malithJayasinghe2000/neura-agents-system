"""The policy engine — where every tool call is authorised.

**Rule 3 of AGENTS.md lives in this file.** Authorisation is code, never a
prompt. A system prompt is guidance and a persuasive user message competes with
it on equal terms; this module competes with nothing, because the model does not
run it and cannot address it.

Eight independent checks, in this order
(docs/architecture/agent-runtime.md §3.3, restated from the security side in
security-model.md §9):

    1. Is the tool registered for this conversation?      no ─► reject
    2. Does the store declare the required capability?    no ─► reject
    3. Does the API key hold the scope?                   no ─► reject
    4. Does tenant policy allow it in this mode?          no ─► reject
    5. Side effect greater than READ?                     yes ─► reject (no queue)
    6. Arguments valid against the JSON schema?           no ─► repairable
    7. Ownership: may this session see this resource?     no ─► escalate
    8. Budget for this conversation?                      no ─► degrade

The order is not arbitrary. The cheap structural checks come first so a
malformed or unauthorised call never reaches argument parsing; ownership comes
after validation because it reads a validated argument; budget comes last
because a call about to be refused anyway should not consume any.

**Every decision is recorded — allowed and rejected alike.** The rejections are
not noise: they are the evidence the injection suite actually passes, because
the eval asserts on what the engine refused rather than on whether a reply
*sounded* like a refusal (evaluation-strategy.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from neura_agent_core.tools.registry import ToolRegistry
from neura_agent_core.tools.spec import ToolContext, ToolSpec
from neura_core import get_logger
from neura_domain import SideEffect

log = get_logger(__name__)


class Outcome(StrEnum):
    """What the engine decided, and what the caller should do about it."""

    ALLOW = "allow"
    """Run it."""

    REJECT = "reject"
    """Refuse and tell the model why. It may choose a different tool."""

    REPAIR = "repair"
    """The arguments were wrong in a fixable way. Feed the error back and retry."""

    ESCALATE = "escalate"
    """Stop the conversation and hand to a human. Used where continuing would
    mean guessing about someone's data."""

    DEGRADE = "degrade"
    """Budget exhausted. Answer without this tool rather than failing outright —
    never a hard error for the shopper (llm-abstraction.md §6)."""


class Check(StrEnum):
    """Which of the eight gates decided. Recorded, so a rejection is diagnosable."""

    REGISTERED = "registered"
    CAPABILITY = "capability"
    SCOPE = "scope"
    TENANT_POLICY = "tenant_policy"
    SIDE_EFFECT = "side_effect"
    ARGUMENTS = "arguments"
    OWNERSHIP = "ownership"
    BUDGET = "budget"


@dataclass(frozen=True, slots=True)
class Decision:
    """One authorisation decision, in full. Goes to the audit log verbatim."""

    outcome: Outcome
    tool_name: str
    check: Check | None = None
    reason: str = ""
    #: Populated only on ALLOW. Validated, coerced, and safe to execute with.
    arguments: BaseModel | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome is Outcome.ALLOW

    def as_model_feedback(self) -> str:
        """What the model is told. Deliberately specific about *what* failed and
        silent about anything it could use to probe further."""
        return f"{self.tool_name} was not run: {self.reason}"


@dataclass(slots=True)
class ConversationBudget:
    """Per-conversation ceilings.

    The per-conversation cap matters more than it looks: without it, one user in
    a loop with a tool-calling agent can burn a tenant's entire monthly budget in
    an afternoon (llm-abstraction.md §6).
    """

    max_tool_calls: int = 4
    calls_used: int = 0

    @property
    def exhausted(self) -> bool:
        return self.calls_used >= self.max_tool_calls

    def spend(self) -> None:
        self.calls_used += 1


class PolicyEngine:
    """Authorises tool calls. Runs outside the model, always."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def authorise(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolContext,
        budget: ConversationBudget | None = None,
    ) -> Decision:
        """Run all eight checks. The first failure decides."""
        decision = self._authorise(tool_name, arguments, ctx, budget)

        # Recorded here rather than at each return, so no check can be added
        # later that quietly skips the audit trail.
        log.info(
            "policy_decision",
            tool=tool_name,
            outcome=decision.outcome.value,
            check=decision.check.value if decision.check else None,
            reason=decision.reason,
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
        )
        return decision

    def _authorise(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        ctx: ToolContext,
        budget: ConversationBudget | None,
    ) -> Decision:
        # ── 1. Registered, and available for *this* conversation ─────────────
        spec = self._registry.get(tool_name)
        if spec is None:
            # Includes the model inventing a plausible-sounding tool name, which
            # small models do regularly.
            return Decision(
                outcome=Outcome.REJECT,
                tool_name=tool_name,
                check=Check.REGISTERED,
                reason="no such tool",
            )

        # ── 2. The store can actually do it ──────────────────────────────────
        missing = spec.requires - ctx.capabilities
        if missing:
            return Decision(
                outcome=Outcome.REJECT,
                tool_name=tool_name,
                check=Check.CAPABILITY,
                reason="this store does not support that",
                details={"missing_capabilities": sorted(c.value for c in missing)},
            )

        # ── 3. The caller's key holds the scope ──────────────────────────────
        if not spec.scopes <= ctx.scopes:
            return Decision(
                outcome=Outcome.REJECT,
                tool_name=tool_name,
                check=Check.SCOPE,
                reason="not permitted for this API key",
                details={"missing_scopes": sorted(spec.scopes - ctx.scopes)},
            )

        # ── 4. Tenant policy ─────────────────────────────────────────────────
        if ctx.allowed_tools is not None and spec.name not in ctx.allowed_tools:
            return Decision(
                outcome=Outcome.REJECT,
                tool_name=tool_name,
                check=Check.TENANT_POLICY,
                reason="disabled for this store",
            )

        # ── 5. Side-effect gate ──────────────────────────────────────────────
        if spec.side_effect is not SideEffect.READ:
            # Unreachable while the registry refuses to register such a tool.
            # Kept because the two defences protect different mistakes: the
            # registry catches a tool declared WRITE, this catches a tool whose
            # declaration changes after registration.
            return Decision(
                outcome=Outcome.REJECT,
                tool_name=tool_name,
                check=Check.SIDE_EFFECT,
                reason="actions that change the store require human approval, "
                "which is not available",
                details={"side_effect": spec.side_effect.value},
            )

        # ── 6. Arguments ─────────────────────────────────────────────────────
        try:
            validated = spec.validate_arguments(arguments)
        except ValidationError as exc:
            # REPAIR, not REJECT: a wrong argument is the model's most common and
            # most fixable mistake, and the bounded repair loop exists for it.
            return Decision(
                outcome=Outcome.REPAIR,
                tool_name=tool_name,
                check=Check.ARGUMENTS,
                reason=_readable(exc),
                details={"errors": exc.errors(include_url=False)},
            )

        # ── 7. Ownership ─────────────────────────────────────────────────────
        if spec.requires_ownership is not None:
            reference = str(getattr(validated, spec.requires_ownership))
            # `scoped_to_session` is passed, not assumed. An authenticated session
            # is trusted with an arbitrary reference *only* for a tool that has
            # declared it filters results by that customer — otherwise a signed-in
            # shopper could read a stranger's order by typing its number, having
            # satisfied every check above (open question A6). Default deny: a tool
            # that omits the declaration simply does not get the blanket trust.
            if not ctx.identity.may_see(reference, tool_scopes_to_session=spec.scoped_to_session):
                # ESCALATE rather than REJECT. Rejecting invites the model to try
                # again with a different reference, which is order enumeration
                # with extra steps. A human takes it from here.
                #
                # The reason is deliberately uniform: it must read the same for a
                # non-existent order and for someone else's order, or the message
                # itself becomes an oracle (security-model.md §3).
                return Decision(
                    outcome=Outcome.ESCALATE,
                    tool_name=tool_name,
                    check=Check.OWNERSHIP,
                    reason="this session has not proven it may see that order",
                    details={"argument": spec.requires_ownership},
                )

        # ── 8. Budget ────────────────────────────────────────────────────────
        if budget is not None and budget.exhausted:
            return Decision(
                outcome=Outcome.DEGRADE,
                tool_name=tool_name,
                check=Check.BUDGET,
                reason=f"tool-call limit of {budget.max_tool_calls} reached for this turn",
                details={"calls_used": budget.calls_used},
            )

        return Decision(
            outcome=Outcome.ALLOW,
            tool_name=tool_name,
            arguments=validated,
        )

    def available(self, ctx: ToolContext) -> list[ToolSpec]:
        return self._registry.available_for(ctx)


def _readable(exc: ValidationError) -> str:
    """A validation error the model can act on.

    Pydantic's default rendering includes URLs and types that waste tokens and
    confuse small models. This keeps the field and the problem.
    """
    parts = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(p) for p in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
