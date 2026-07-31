"""What gets evaluated.

The harness is built before the agent exists (docs/roadmap.md — milestone 1.4
deliberately precedes 1.10). ``EvalTarget`` is the seam: anything that can take a
case and return a response can be scored, so the real agent plugs in later with
no change here.

``AgentResponse`` mirrors what the agent runtime already records per run, so
wiring it up is a mapping rather than new instrumentation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from neura_evals.dataset import EvalCase


class ToolInvocation(BaseModel):
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    authorised: bool = Field(
        default=True,
        description=(
            "Whether the policy engine ALLOWED this call. Adversarial cases assert "
            "on this rather than on reply text — a reply can sound like a refusal "
            "while a tool was quietly invoked."
        ),
    )
    error: str | None = None


class AgentResponse(BaseModel):
    """One agent run, as the harness needs to see it."""

    reply: str
    intent: str | None = None
    tools_called: list[ToolInvocation] = Field(default_factory=list)
    retrieved_context: list[str] = Field(
        default_factory=list, description="The evidence the groundedness judge scores against"
    )
    escalated: bool = False
    refused: bool = False
    #: The guard recognised a named attack and the turn ended at `blocked` —
    #: no person, no tools, no model call after the guard (ADR-0012).
    blocked: bool = False
    #: The agent's own outbound filter found personal data in the reply that
    #: nothing in the turn accounted for. See `Expectation.pii_leaked` for what
    #: this is and is not evidence of.
    pii_leaked: bool = False
    latency_ms: int = 0
    cost_usd: Decimal = Decimal("0")
    tokens_used: int = 0
    structured_repairs: int = Field(
        default=0, description="JSON repair retries — the early warning that a model is unsuitable"
    )
    #: The model provider could not be reached at all. **Not a result.** The
    #: case is skipped rather than scored, for the same reason an unreachable
    #: judge is skipped rather than counted as a hallucination.
    #:
    #: Measured 2026-07-31: Ollama died mid-run, the graph degraded correctly to
    #: escalation on every case, and the suite reported intent accuracy 0.00 and
    #: tool selection 0.00 — a total agent collapse that was a dead server. The
    #: graph behaved perfectly; the number was a lie (open question E6).
    infrastructure_error: str | None = None
    error: str | None = None
    not_run: bool = Field(
        default=False,
        description=(
            "True when no agent was executed at all (`--no-agent`). **Not a failure** — "
            "the case is unmeasured, and it is skipped rather than scored.\n\n"
            "The distinction matters because `--no-agent` is part of `make check`, which "
            "runs before every push. Thirty-five red crosses that are not failures teach "
            "the reader to skim past red, and the next time they are real nobody looks."
        ),
    )

    @property
    def unauthorised_tool_calls(self) -> int:
        return sum(1 for t in self.tools_called if not t.authorised)

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools_called]

    @property
    def evidence(self) -> str:
        parts = list(self.retrieved_context)
        parts += [
            f"tool {t.name}({t.arguments}) -> {'ok' if not t.error else t.error}"
            for t in self.tools_called
        ]
        return "\n\n".join(parts)


@runtime_checkable
class EvalTarget(Protocol):
    """Anything scoreable. The agent implements this in milestone 1.11."""

    name: str

    async def run(self, case: EvalCase) -> AgentResponse: ...


class NotImplementedTarget:
    """No agent. Used by ``--no-agent``, and when none is installed.

    Returns an explicit non-result rather than a plausible-looking empty
    response, so a run against it cannot be mistaken for a real one. ``--no-agent``
    is how the datasets and the scoring logic are validated with no model call
    and no cost.

    Every case is **skipped**, not failed. Marking them failed was the first
    version and it was wrong for the same reason a rate-limited judge must not be
    scored as a hallucination: it states an outcome that was never measured. It
    also put thirty-five red crosses in ``make check``, which runs before every
    push — and a command that is always partly red is a command whose red stops
    meaning anything.
    """

    name = "no-agent"

    async def run(self, case: EvalCase) -> AgentResponse:
        return AgentResponse(
            reply="",
            not_run=True,
            error=(
                "No agent was run (--no-agent, or no installed agent advertises a "
                "'neura.eval_targets' entry point). This is not a result."
            ),
        )
