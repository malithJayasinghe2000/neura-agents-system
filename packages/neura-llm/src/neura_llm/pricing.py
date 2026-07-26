"""Token cost.

Local inference costs nothing, but tokens and latency are still recorded. That
is deliberate: without local usage data we could not model what a workload
*would* cost on a cloud provider before switching — which is exactly the
decision the role map exists to support
(docs/architecture/llm-abstraction.md §3).

Cloud prices are configured per deployment rather than hard-coded, because
published prices change and a stale constant in the codebase silently produces
wrong margin figures.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

from neura_core import get_logger
from neura_llm.types import Usage

log = get_logger(__name__)

_MILLION = Decimal("1000000")


class PriceTable:
    """Per-million-token prices, keyed by model name.

    Loaded from ``LLM_PRICING_JSON``:

        {"model-name": {"input": 0.15, "output": 0.60}}

    An unknown model costs 0 and is logged once. Reporting an unknown cost as
    zero is honest; guessing a price would quietly corrupt the margin model.
    """

    def __init__(self, prices: dict[str, dict[str, Decimal]] | None = None) -> None:
        self._prices = prices or {}
        self._warned: set[str] = set()

    @classmethod
    def from_env(cls) -> PriceTable:
        raw = os.getenv("LLM_PRICING_JSON")
        if not raw:
            return cls()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log.error("pricing_json_invalid", detail="LLM_PRICING_JSON is not valid JSON")
            return cls()
        return cls(
            {
                model: {
                    "input": Decimal(str(values.get("input", 0))),
                    "output": Decimal(str(values.get("output", 0))),
                }
                for model, values in parsed.items()
            }
        )

    def cost(self, *, model: str, usage: Usage, is_local: bool) -> Decimal:
        if is_local:
            return Decimal("0")

        prices = self._prices.get(model)
        if prices is None:
            if model not in self._warned:
                self._warned.add(model)
                log.warning(
                    "model_price_unknown",
                    model=model,
                    detail="Cost recorded as 0. Set LLM_PRICING_JSON to track spend.",
                )
            return Decimal("0")

        return (
            Decimal(usage.prompt_tokens) * prices["input"]
            + Decimal(usage.completion_tokens) * prices["output"]
        ) / _MILLION
