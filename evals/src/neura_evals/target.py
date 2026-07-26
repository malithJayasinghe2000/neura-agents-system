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
    latency_ms: int = 0
    cost_usd: Decimal = Decimal("0")
    tokens_used: int = 0
    structured_repairs: int = Field(
        default=0, description="JSON repair retries — the early warning that a model is unsuitable"
    )
    error: str | None = None

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
    """Placeholder until the agent exists.

    Returns an explicit error rather than a plausible-looking empty response, so
    a run against it cannot be mistaken for a real result.
    """

    name = "not-implemented"

    async def run(self, case: EvalCase) -> AgentResponse:
        return AgentResponse(
            reply="",
            error="No agent is wired up yet — Phase 1 milestone 1.11. See docs/roadmap.md",
        )
