"""Request and response types.

Provider-neutral by design: nothing here names a vendor, so swapping providers
never changes a caller's code.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    """Message author."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> Message:
        return cls(role=Role.ASSISTANT, content=content)


class ToolSpec(BaseModel):
    """A tool offered to the model, as a JSON schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]


class ToolCall(BaseModel):
    """A tool the model asked to invoke.

    Asking is not permission: every call is authorised by the policy engine, in
    code, before anything executes (docs/architecture/security-model.md §9).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message]
    tools: list[ToolSpec] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    stop: list[str] = Field(default_factory=list)
    seed: int | None = Field(
        default=None, description="Set in evals so runs are as reproducible as the model allows"
    )
    reasoning_effort: str | None = Field(
        default=None,
        description=(
            "How much a reasoning model should think before answering. Sent only when "
            "set, because most models do not accept the parameter at all.\n\n"
            "Worth understanding before using: on a reasoning model, `max_tokens` is a "
            "budget for THINKING PLUS the answer, and thinking comes first. A ceiling "
            "sized for the reply therefore produces `finish_reason=length` and EMPTY "
            "content — no error, no warning, just an answer that never arrives. "
            "`reasoning_effort='none'` is how a caller that wants a short grounded "
            "answer rather than deliberation avoids paying for it.\n\n"
            "The accepted values are the provider's, not ours. Ollama understands "
            "'none'; cloud APIs generally take 'low'/'medium'/'high' and may reject "
            "'none'. Verify it at model-swap time — that is what the comparison run in "
            "llm-abstraction.md §8 is for."
        ),
    )


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


class ChatResponse(BaseModel):
    """One completion, with everything needed to meter and audit it."""

    model_config = ConfigDict(extra="forbid")

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost_usd: Decimal = Field(
        default=Decimal("0"),
        description=(
            "Zero for local models. Still recorded, so a workload's cloud cost can "
            "be modelled BEFORE switching — which is the decision the role map exists to support."
        ),
    )
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    finish_reason: FinishReason = FinishReason.UNKNOWN
    structured_repairs: int = Field(
        default=0, description="JSON repair retries needed. A rising rate means a bad role fit."
    )

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class ChatChunk(BaseModel):
    """A streaming delta."""

    model_config = ConfigDict(extra="forbid")

    delta: str = ""
    finish_reason: FinishReason | None = None


class EmbeddingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vectors: list[list[float]]
    model: str
    dimensions: int
    usage: Usage = Field(default_factory=Usage)
    cost_usd: Decimal = Decimal("0")

    def __len__(self) -> int:
        return len(self.vectors)
