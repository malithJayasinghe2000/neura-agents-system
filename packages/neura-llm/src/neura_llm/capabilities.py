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

    STREAMING = "streaming"
    VISION = "vision"
    LOGPROBS = "logprobs"


# Ollama supports constrained decoding, which is the single most important fact
# for making the local path viable — most local models therefore reach the
# strongest structured-output tier. Tool-calling support varies by model, so it
# is decided per model below rather than assumed for the provider.
_OLLAMA_BASE = frozenset(
    {LLMCapability.JSON_SCHEMA_MODE, LLMCapability.JSON_MODE, LLMCapability.STREAMING}
)

# Local models with reliable native tool calling. Conservative on purpose: a
# model wrongly listed here produces confusing runtime failures, whereas a model
# wrongly omitted just takes the slower fallback path.
_OLLAMA_TOOL_CALLING_FAMILIES = ("llama3.1", "llama3.2", "llama3.3", "qwen2.5", "qwen3", "mistral")

_CLOUD_DEFAULT = frozenset(
    {
        LLMCapability.NATIVE_TOOL_CALLING,
        LLMCapability.PARALLEL_TOOL_CALLS,
        LLMCapability.JSON_SCHEMA_MODE,
        LLMCapability.JSON_MODE,
        LLMCapability.STREAMING,
    }
)


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
