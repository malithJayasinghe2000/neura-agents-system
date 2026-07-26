"""neura-llm — LLM provider abstraction by model role.

Callers ask for a **role**, never a model:

    client = LLMClient.from_role_map_name("ollama-dev")
    response = await client.chat(ModelRole.REASONER, request)

Model identifiers live in exactly one place: the role map. Swapping the map
swaps every model at once — development on local Ollama, production on a cloud
API, or a hybrid keeping the cheap high-volume roles local — with no code change
(docs/architecture/adr/0006-llm-model-roles.md).

Every provider is driven through the OpenAI-compatible interface, which Ollama
also exposes, so there is one code path rather than a branch per vendor. A
provider we never planned for plugs in as a base URL and a model name.
"""

from neura_llm.capabilities import LLMCapability, capabilities_for
from neura_llm.client import LLMClient
from neura_llm.errors import (
    EmbeddingDimensionMismatchError,
    LLMError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RoleNotConfiguredError,
    StructuredOutputError,
)
from neura_llm.pricing import PriceTable
from neura_llm.provider import LLMProvider, OpenAICompatibleProvider
from neura_llm.roles import (
    BUILTIN_ROLE_MAPS,
    ModelRole,
    ProviderConfig,
    RoleConfig,
    RoleMap,
    load_role_map,
)
from neura_llm.structured import StructuredResult, generate_structured
from neura_llm.types import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingResult,
    FinishReason,
    Message,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)

__all__ = [
    "BUILTIN_ROLE_MAPS",
    "ChatChunk",
    "ChatRequest",
    "ChatResponse",
    "EmbeddingDimensionMismatchError",
    "EmbeddingResult",
    "FinishReason",
    "LLMCapability",
    "LLMClient",
    "LLMError",
    "LLMProvider",
    "Message",
    "ModelRole",
    "OpenAICompatibleProvider",
    "PriceTable",
    "ProviderConfig",
    "ProviderRateLimitedError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "Role",
    "RoleConfig",
    "RoleMap",
    "RoleNotConfiguredError",
    "StructuredOutputError",
    "StructuredResult",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "capabilities_for",
    "generate_structured",
    "load_role_map",
]
