"""What a provider can actually do.

Capabilities are **declared, not assumed** (docs/architecture/llm-abstraction.md
§1.3). Providers differ in native tool calling and in how strictly they can
enforce a JSON schema, and the difference is largest exactly where it hurts:
between a small local model and a frontier one.

The runtime adapts to what a provider declares rather than assuming the strongest
behaviour and failing at request time.
"""

from __future__ import annotations

from enum import StrEnum


class LLMCapability(StrEnum):
    NATIVE_TOOL_CALLING = "tools.native"
    """OpenAI-style ``tool_calls`` in the response."""

    PARALLEL_TOOL_CALLS = "tools.parallel"
    """Several tool calls in one turn."""

    JSON_SCHEMA_MODE = "json.schema"
    """Server-side constrained decoding. Malformed output becomes impossible."""

    JSON_MODE = "json.object"
    """Valid JSON guaranteed, but the shape is not enforced."""

    REASONING_EFFORT_NONE = "reasoning.none"
    """``reasoning_effort="none"`` is accepted — the caller can switch thinking off.

    Declared rather than assumed, because the two paths this project ships
    disagree about it and the disagreement is a hard 400 rather than a
    degradation. Ollama understands ``"none"``. **Gemini's OpenAI-compatible
    endpoint rejects it with `400 INVALID_ARGUMENT`** — measured 2026-08-27,
    with ``"low"`` and omission both accepted on the same model in the same
    minute.

    `ChatRequest.reasoning_effort` predicted this in as many words and said to
    verify it at model-swap time. It was verified by the swap: every `compose`
    call in SELL's first cloud run 400'd, six of fourteen cases were skipped as
    unreachable, and the agent could not be measured on a cloud model at all.

    **Dropping the parameter is not the fallback.** A reasoning model left to
    think spends `max_tokens` on thinking first and returns `finish_reason=length`
    with empty content — the exact failure ``"none"`` exists to prevent, and it
    arrives looking like a model that had nothing to say. The fallback is the
    lowest value the provider *does* accept.
    """

    STREAMING = "streaming"
    VISION = "vision"
    LOGPROBS = "logprobs"


# Ollama supports constrained decoding, which is the single most important fact
# for making the local path viable — most local models therefore reach the
# strongest structured-output tier. Tool-calling support varies by model, so it
# is decided per model below rather than assumed for the provider.
_OLLAMA_BASE = frozenset(
    {
        LLMCapability.JSON_SCHEMA_MODE,
        LLMCapability.JSON_MODE,
        LLMCapability.STREAMING,
        LLMCapability.REASONING_EFFORT_NONE,
    }
)

# Local models with reliable native tool calling. Conservative on purpose: a
# model wrongly listed here produces confusing runtime failures, whereas a model
# wrongly omitted just takes the slower fallback path.
_OLLAMA_TOOL_CALLING_FAMILIES = ("llama3.1", "llama3.2", "llama3.3", "qwen2.5", "qwen3", "mistral")

#: Note what is **absent**: ``REASONING_EFFORT_NONE``. The conservative default
#: is that a cloud endpoint does not accept ``"none"``, because being wrong in
#: that direction costs one notch of extra thinking and being wrong in the other
#: costs every affected call.
_CLOUD_DEFAULT = frozenset(
    {
        LLMCapability.NATIVE_TOOL_CALLING,
        LLMCapability.PARALLEL_TOOL_CALLS,
        LLMCapability.JSON_SCHEMA_MODE,
        LLMCapability.JSON_MODE,
        LLMCapability.STREAMING,
    }
)

#: What ``"none"`` becomes on a provider that will not take it: the least
#: thinking the provider offers, never nothing at all.
LOWEST_REASONING_EFFORT = "low"


def capabilities_for(*, provider_name: str, model: str) -> frozenset[LLMCapability]:
    """Best-known capabilities for a provider/model pair.

    Overridable per deployment via ``ProviderConfig.capabilities`` — a
    self-hosted gateway may support more or less than we assume here.
    """
    name = provider_name.lower()
    model_lower = model.lower()

    if name == "ollama":
        caps = set(_OLLAMA_BASE)
        if any(family in model_lower for family in _OLLAMA_TOOL_CALLING_FAMILIES):
            caps.add(LLMCapability.NATIVE_TOOL_CALLING)
        return frozenset(caps)

    # Any other OpenAI-compatible endpoint: assume the common modern feature set.
    return _CLOUD_DEFAULT
