"""LLM-layer errors.

All inherit from ``NeuraError`` so they carry a stable code to the API boundary.
Each one exists because a caller needs to react differently: retry, degrade, or
escalate.
"""

from __future__ import annotations

from neura_core import NeuraError


class LLMError(NeuraError):
    code = "LLM_ERROR"
    error_type = "api_error"
    http_status = 502


class ProviderUnavailableError(LLMError):
    """The inference backend is unreachable or erroring.

    Caller should fall back to a secondary provider, or degrade to escalate-only.
    """

    code = "LLM_PROVIDER_UNAVAILABLE"
    http_status = 503


class ProviderTimeoutError(LLMError):
    code = "LLM_TIMEOUT"
    http_status = 504


class ProviderRateLimitedError(LLMError):
    code = "LLM_RATE_LIMITED"
    error_type = "rate_limit_error"
    http_status = 429


class StructuredOutputError(LLMError):
    """The model could not produce schema-valid output within the repair budget.

    Not retried further by the caller: the graph node handles it by escalating.
    A rising rate of these is the early warning that a model is unsuitable for a
    role (docs/architecture/llm-abstraction.md §4.2).
    """

    code = "LLM_STRUCTURED_OUTPUT_FAILED"


class RoleNotConfiguredError(LLMError):
    """A role was requested that the active role map does not define."""

    code = "LLM_ROLE_NOT_CONFIGURED"
    http_status = 500


class EmbeddingDimensionMismatchError(LLMError):
    """Vectors from different embedding models are not comparable.

    Raised loudly rather than allowed to silently degrade retrieval — the
    failure this guards against produces no error at all, just quietly worse
    answers (docs/architecture/llm-abstraction.md §5).
    """

    code = "LLM_EMBEDDING_DIMENSION_MISMATCH"
    http_status = 500
