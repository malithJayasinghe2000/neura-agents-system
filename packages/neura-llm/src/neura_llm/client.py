"""The client callers actually use.

Everything above this layer asks for a **role** and gets an answer. It never
learns which model served it, which is what makes the dev→production swap a
config change rather than a refactor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

from neura_core import get_logger
from neura_llm.capabilities import LOWEST_REASONING_EFFORT, LLMCapability
from neura_llm.errors import EmbeddingDimensionMismatchError
from neura_llm.pricing import PriceTable
from neura_llm.provider import OpenAICompatibleProvider
from neura_llm.roles import ModelRole, RoleMap, load_role_map
from neura_llm.structured import StructuredResult, generate_structured
from neura_llm.types import ChatChunk, ChatRequest, ChatResponse, EmbeddingResult

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Resolves roles to providers and meters every call."""

    def __init__(self, role_map: RoleMap, *, prices: PriceTable | None = None) -> None:
        self._role_map = role_map
        self._prices = prices or PriceTable.from_env()
        self._providers: dict[str, OpenAICompatibleProvider] = {}
        #: Roles already reported as downgraded, so the log line is said once
        #: rather than on every call.
        self._effort_downgraded: set[ModelRole] = set()

    @classmethod
    def from_role_map_name(cls, name: str) -> LLMClient:
        return cls(load_role_map(name))

    @property
    def role_map_name(self) -> str:
        return self._role_map.name

    @property
    def embedding_model(self) -> str:
        """Names the vector namespace.

        Vectors from different embedding models are not comparable, so every
        stored chunk is scoped by (tenant, this value). Full reasoning in
        docs/architecture/llm-abstraction.md §5.
        """
        return self._role_map.embedding_model

    @property
    def is_fully_local(self) -> bool:
        """True when no request leaves the machine — the sovereign property."""
        return self._role_map.is_fully_local

    def capabilities(self, role: ModelRole) -> frozenset[LLMCapability]:
        return self._role_map.capabilities(role)

    def model_for(self, role: ModelRole) -> str:
        _, role_config = self._role_map.resolve(role)
        return role_config.model

    def _provider_for(self, role: ModelRole) -> tuple[OpenAICompatibleProvider, str, ChatRequest]:
        provider_config, role_config = self._role_map.resolve(role)
        provider = self._providers.get(provider_config.name)
        if provider is None:
            provider = OpenAICompatibleProvider(provider_config, prices=self._prices)
            self._providers[provider_config.name] = provider
        defaults = ChatRequest(
            messages=[],
            temperature=role_config.temperature,
            max_tokens=role_config.max_tokens,
            reasoning_effort=role_config.reasoning_effort,
        )
        return provider, role_config.model, defaults

    def _apply_defaults(self, request: ChatRequest, defaults: ChatRequest) -> ChatRequest:
        """Role defaults fill gaps; an explicit value on the request always wins."""
        updates: dict[str, object] = {}
        if request.temperature is None:
            updates["temperature"] = defaults.temperature
        if request.max_tokens is None and defaults.max_tokens is not None:
            updates["max_tokens"] = defaults.max_tokens
        if request.reasoning_effort is None and defaults.reasoning_effort is not None:
            updates["reasoning_effort"] = defaults.reasoning_effort
        return request.model_copy(update=updates) if updates else request

    def _apply_capabilities(self, request: ChatRequest, role: ModelRole) -> ChatRequest:
        """Rewrite anything the provider serving this role cannot accept.

        Today that is one parameter, and it is a hard failure rather than a
        degradation: ``reasoning_effort="none"`` is understood by Ollama and
        **rejected with 400 by Gemini's OpenAI-compatible endpoint**. Measured
        2026-08-27, when it took out every `compose` call in SELL's first cloud
        run and six of fourteen cases were skipped as provider-unreachable.

        It is downgraded to the lowest value the provider does take, never
        dropped. A caller asking for ``"none"`` is asking not to pay for
        deliberation — and a reasoning model with no ceiling on its thinking
        spends `max_tokens` before writing a character, which returns empty
        content and `finish_reason=length` and reads as a model with nothing to
        say (`ChatRequest.reasoning_effort`).

        Same shape as the `json_schema` → `json_object` fallback in
        `structured.py`: the runtime adapts to what a provider declares instead
        of assuming the strongest behaviour and failing at request time
        (llm-abstraction.md §1.3).
        """
        if request.reasoning_effort != "none":
            return request
        if LLMCapability.REASONING_EFFORT_NONE in self._role_map.capabilities(role):
            return request

        if role not in self._effort_downgraded:
            self._effort_downgraded.add(role)
            log.info(
                "reasoning_effort_downgraded",
                role=role.value,
                requested="none",
                using=LOWEST_REASONING_EFFORT,
                detail="the provider for this role does not accept 'none'",
            )
        return request.model_copy(update={"reasoning_effort": LOWEST_REASONING_EFFORT})

    async def chat(self, role: ModelRole, request: ChatRequest) -> ChatResponse:
        provider, model, defaults = self._provider_for(role)
        prepared = self._apply_capabilities(self._apply_defaults(request, defaults), role)
        response = await provider.chat(prepared, model=model)
        log.info(
            "llm_call",
            role=role.value,
            model=model,
            provider=response.provider,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            cost_usd=str(response.cost_usd),
            latency_ms=response.latency_ms,
        )
        return response

    async def chat_stream(self, role: ModelRole, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        provider, model, defaults = self._provider_for(role)
        async for chunk in provider.chat_stream(
            self._apply_capabilities(self._apply_defaults(request, defaults), role), model=model
        ):
            yield chunk

    async def chat_structured[ModelT: BaseModel](
        self, role: ModelRole, request: ChatRequest, schema_type: type[ModelT]
    ) -> StructuredResult[ModelT]:
        provider, model, defaults = self._provider_for(role)
        result = await generate_structured(
            provider,
            self._apply_capabilities(self._apply_defaults(request, defaults), role),
            schema_type,
            model=model,
            capabilities=self._role_map.capabilities(role),
        )
        log.info(
            "llm_structured_call",
            role=role.value,
            model=model,
            schema=schema_type.__name__,
            attempts=result.attempts,
            repaired=result.needed_repair,
            cost_usd=str(result.response.cost_usd),
        )
        return result

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed with the configured EMBEDDER.

        Verifies the returned dimensionality against the role map. A mismatch is
        raised rather than tolerated: the failure it guards against produces no
        error at all, only quietly worse retrieval.
        """
        provider, model, _ = self._provider_for(ModelRole.EMBEDDER)
        result = await provider.embed(texts, model=model)

        _, role_config = self._role_map.resolve(ModelRole.EMBEDDER)
        expected = role_config.dimensions
        if expected is not None and result.dimensions and result.dimensions != expected:
            raise EmbeddingDimensionMismatchError(
                f"{model} returned {result.dimensions}-dimensional vectors, "
                f"but the role map declares {expected}. Vectors of different sizes are "
                "not comparable — fix the config or reindex.",
                details={
                    "model": model,
                    "expected_dimensions": expected,
                    "actual_dimensions": result.dimensions,
                },
            )
        return result

    async def health(self) -> dict[str, str]:
        """Per-role reachability. Used by ``/v1/health/ready`` and the smoke test."""
        status: dict[str, str] = {}
        for role in ModelRole:
            try:
                provider, model, _ = self._provider_for(role)
                status[role.value] = f"{provider.name}:{model}"
            except Exception as exc:
                status[role.value] = f"error: {exc}"
        return status
