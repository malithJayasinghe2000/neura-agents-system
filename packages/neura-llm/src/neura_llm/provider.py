"""The provider interface, and its one implementation.

There is a single implementation on purpose. Ollama exposes an OpenAI-compatible
``/v1`` endpoint, so local and cloud inference are the same code path — there is
no ``if provider == "ollama"`` anywhere in this codebase
(docs/architecture/llm-abstraction.md §1.2).

That is also why a provider we never planned for — Gemini, say — plugs in as a
base URL and a model name, with no new code.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

import openai
from openai import AsyncOpenAI

from neura_core import get_logger
from neura_llm.capabilities import LLMCapability
from neura_llm.errors import (
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from neura_llm.pricing import PriceTable
from neura_llm.roles import ProviderConfig
from neura_llm.types import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingResult,
    FinishReason,
    Message,
    ToolCall,
    Usage,
)

log = get_logger(__name__)


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    capabilities: frozenset[LLMCapability]

    async def chat(self, request: ChatRequest, *, model: str, **kwargs: Any) -> ChatResponse: ...

    async def chat_stream(
        self, request: ChatRequest, *, model: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]: ...

    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult: ...


def _to_wire(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.name:
        payload["name"] = message.name
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    return payload


def _finish_reason(raw: str | None) -> FinishReason:
    try:
        return FinishReason(raw) if raw else FinishReason.UNKNOWN
    except ValueError:
        return FinishReason.UNKNOWN


class OpenAICompatibleProvider:
    """Talks to any OpenAI-compatible endpoint."""

    def __init__(self, config: ProviderConfig, *, prices: PriceTable | None = None) -> None:
        self._config = config
        self._prices = prices or PriceTable.from_env()
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            # Some local servers accept no key; the client library still requires
            # a non-empty string.
            api_key=config.api_key or "not-needed",
            timeout=config.timeout_s,
            max_retries=0,  # retries are the caller's decision, with its own budget
        )

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def is_local(self) -> bool:
        return self._config.is_local

    async def chat(self, request: ChatRequest, *, model: str, **kwargs: Any) -> ChatResponse:
        started = time.perf_counter()
        payload = self._build_payload(request, model=model, **kwargs)

        try:
            completion = await self._client.chat.completions.create(**payload)
        except Exception as exc:
            raise self._translate(exc, model=model) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        choice = completion.choices[0]

        tool_calls: list[ToolCall] = []
        for raw_call in choice.message.tool_calls or []:
            tool_calls.append(
                ToolCall(
                    id=raw_call.id,
                    name=raw_call.function.name,
                    arguments=_safe_json(raw_call.function.arguments),
                )
            )

        usage = Usage(
            prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
            completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
        )

        return ChatResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            usage=usage,
            cost_usd=self._prices.cost(model=model, usage=usage, is_local=self.is_local),
            model=model,
            provider=self.name,
            latency_ms=latency_ms,
            finish_reason=_finish_reason(choice.finish_reason),
        )

    async def chat_stream(
        self, request: ChatRequest, *, model: str, **kwargs: Any
    ) -> AsyncIterator[ChatChunk]:
        payload = self._build_payload(request, model=model, **kwargs)
        payload["stream"] = True

        try:
            stream = await self._client.chat.completions.create(**payload)
            async for event in stream:
                if not event.choices:
                    continue
                choice = event.choices[0]
                yield ChatChunk(
                    delta=choice.delta.content or "",
                    finish_reason=_finish_reason(choice.finish_reason)
                    if choice.finish_reason
                    else None,
                )
        except Exception as exc:
            raise self._translate(exc, model=model) from exc

    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        try:
            response = await self._client.embeddings.create(model=model, input=texts)
        except Exception as exc:
            raise self._translate(exc, model=model) from exc

        vectors = [item.embedding for item in response.data]
        usage = Usage(prompt_tokens=response.usage.prompt_tokens if response.usage else 0)

        return EmbeddingResult(
            vectors=vectors,
            model=model,
            dimensions=len(vectors[0]) if vectors else 0,
            usage=usage,
            cost_usd=self._prices.cost(model=model, usage=usage, is_local=self.is_local),
        )

    def _build_payload(self, request: ChatRequest, *, model: str, **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [_to_wire(m) for m in request.messages],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stop:
            payload["stop"] = request.stop
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.reasoning_effort is not None:
            # Sent only when asked for. Most models reject the parameter, and a
            # default here would break every provider that has never heard of it.
            payload["reasoning_effort"] = request.reasoning_effort
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        payload.update(kwargs)
        return payload

    def _translate(self, exc: Exception, *, model: str) -> Exception:
        """Map provider exceptions onto ours, so callers branch on one hierarchy."""
        details = {"provider": self.name, "model": model}

        if isinstance(exc, openai.RateLimitError):
            return ProviderRateLimitedError(
                f"{self.name} rate limited the request.", details=details
            )
        if isinstance(exc, openai.APITimeoutError):
            return ProviderTimeoutError(f"{self.name} timed out.", details=details)
        if isinstance(exc, openai.APIConnectionError):
            hint = (
                " Is Ollama running? Try: ollama serve"
                if self.is_local
                else " Check the base URL and network."
            )
            return ProviderUnavailableError(
                f"Could not reach {self.name} at {self._config.base_url}.{hint}",
                details=details,
            )
        if isinstance(exc, openai.NotFoundError):
            hint = f" Try: ollama pull {model}" if self.is_local else ""
            return ProviderUnavailableError(
                f"Model {model!r} not found on {self.name}.{hint}", details=details
            )
        if isinstance(exc, openai.APIStatusError):
            return ProviderUnavailableError(
                f"{self.name} returned {exc.status_code}.", details=details
            )
        return ProviderUnavailableError(f"{self.name} call failed: {exc}", details=details)


def _safe_json(raw: str) -> dict[str, Any]:
    """Parse tool arguments, tolerating a model that emits malformed JSON."""
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("tool_arguments_unparseable", raw=raw[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}
