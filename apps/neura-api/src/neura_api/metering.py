"""Counting what a turn cost, without the agent having to know it is counted.

**This is the missing half of open question P5.** Milestone 1.13 built the usage
meter, the atomic daily rollup, the budget ladder and the reader, and nothing
called ``UsageMeter.record`` — so ``spend_today`` was always zero, every tenant
was ``NORMAL``, and every ceiling in ADR-0015 was untriggerable. P5 names where
the numbers have to come from: *turns, LLM calls and ``cost_usd`` from the
client, tool calls and escalations from the graph*.

This is the client half. It is a wrapper rather than a change to any node, and
the distinction matters more than it looks:

* **The graph is untouched.** Only ``compose`` accumulates cost into
  ``AgentState``, so a per-node change would have meant editing five nodes across
  two packages to catch ``route``, ``plan``, ``triage`` and ``verify`` — five
  behaviour-adjacent edits to an agent under Rule 4, to count something.
* **It cannot miss a call.** Whatever a node asks for, it asks this object for,
  so a node added tomorrow is metered without anyone remembering to meter it.
* **It cannot change an answer.** Every method returns the provider's own object,
  unmodified, and every argument is forwarded untouched. ``test_metering.py``
  asserts identity — ``response is inner_response`` — because "it just passes
  through" is exactly the kind of claim that stops being true during a refactor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from neura_core import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class LLMSpend:
    """What one turn asked of the models."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class MeteredLLM:
    """An LLM client that counts, and changes nothing else.

    Constructed per turn around the process-wide client, so the counters belong
    to one conversation and cannot leak between shoppers. The underlying client
    — with its provider connections and its price table — is shared, because
    building one per request would open a new HTTP connection pool per shopper.

    Typed loosely for the same reason ``Runtime.llm`` is: an agent must be able
    to stub its model without installing a provider package.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.spend = LLMSpend()

    # ── Passthrough surface ──────────────────────────────────────────────────
    #
    # Explicit methods rather than `__getattr__`. A catch-all would forward
    # future methods silently *and unmetered*, which is the failure this class
    # exists to prevent: a new call path that costs money and reports nothing.

    @property
    def role_map_name(self) -> str:
        return str(self._inner.role_map_name)

    @property
    def embedding_model(self) -> str:
        return str(self._inner.embedding_model)

    @property
    def is_fully_local(self) -> bool:
        return bool(self._inner.is_fully_local)

    def capabilities(self, role: Any) -> Any:
        return self._inner.capabilities(role)

    def model_for(self, role: Any) -> str:
        return str(self._inner.model_for(role))

    async def chat(self, role: Any, request: Any) -> Any:
        response = await self._inner.chat(role, request)
        self._record(response)
        return response

    async def chat_structured(self, role: Any, request: Any, schema_type: Any) -> Any:
        result = await self._inner.chat_structured(role, request, schema_type)
        # `generate_structured` folds a repair attempt's tokens into the
        # response it returns, so this counts the repair without double-counting
        # the original. `attempts` is the honest call count.
        self._record(result.response, calls=int(getattr(result, "attempts", 1)))
        return result

    async def chat_stream(self, role: Any, request: Any) -> AsyncIterator[Any]:
        # Not metered, and nothing calls it. Streaming deltas carry no usage
        # block until the final chunk, and ADR-0016 means no node streams to a
        # shopper anyway. Left as a passthrough rather than removed so a future
        # caller finds a working method — and this comment.
        async for chunk in self._inner.chat_stream(role, request):
            yield chunk

    async def embed(self, texts: list[str]) -> Any:
        result = await self._inner.embed(texts)
        self._record(result)
        return result

    async def health(self) -> dict[str, str]:
        status: dict[str, str] = await self._inner.health()
        return status

    def _record(self, response: Any, *, calls: int = 1) -> None:
        """Add one provider response to the running total.

        Every field is read defensively. A stubbed client in a test returns
        something without a ``usage`` block, and a metering wrapper that raised
        on it would make the meter a reason tests fail rather than a thing they
        check.
        """
        usage = getattr(response, "usage", None)
        self.spend.calls += calls
        self.spend.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.spend.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        cost = getattr(response, "cost_usd", None)
        if cost is not None:
            self.spend.cost_usd += Decimal(str(cost))


__all__ = ["LLMSpend", "MeteredLLM"]
