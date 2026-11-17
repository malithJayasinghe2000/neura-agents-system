"""What a date's plan should be about, suggested 28 days before. ADR-0078 §1.

The night run asks this **before** any plan is written: which of the shop's
products in stock fit the date, **or none**. The owner then chooses (products,
a greeting only, or skip), and only then is the plan written (D21).

| The date | The suggestion | A model call? |
|:--|:--|:--|
| Vesak or Poson | a greeting only (``religious``) | no, code |
| no product in stock | a greeting only (``no_products``) | no |
| any other | 1 to 3 products (``fit``), or a greeting (``none_fit``) | one, two if refused |
| refused twice | nothing (``could_not``): the owner chooses | two |

**The model answers ids only**, from the list it was given, so nothing it writes
reaches the owner's page: the page says why in code's own words. :func:`check`
refuses an id it was not given, a repeated id, or more than three.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from neura_agent_grow.campaign import MAX_SHOWN, CatalogueItem
from neura_core import get_logger
from neura_llm import ChatRequest, Message, ModelRole

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SuggestInput:
    """What the model is given for one date."""

    shop: str
    name: str
    day: date
    products: Sequence[CatalogueItem] = ()
    #: The shop's own date (its birthday, a sale), not a festival.
    own: bool = False
    #: Vesak or Poson: a greeting, with no call (ADR-0078 §1).
    greeting_only: bool = False


class SuggestAnswer(BaseModel):
    """What the model returns: ids only."""

    model_config = ConfigDict(extra="ignore")

    product_ids: list[str] = Field(
        default_factory=list, description="0 to 3 ids copied from the product list."
    )


@dataclass(frozen=True, slots=True)
class Suggestion:
    """What is stored as ``calendar_plans.suggestion``."""

    kind: str
    reason: str
    products: tuple[str, ...] = ()

    def stored(self) -> dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason, "products": list(self.products)}


@dataclass(frozen=True, slots=True)
class SuggestResult:
    suggestion: Suggestion | None = None
    calls: int = 0
    #: Set when the model could not be reached: a retry, not a result.
    error: str = ""
    #: What the model said before the check, for the eval only.
    raw: tuple[SuggestAnswer, ...] = field(default_factory=tuple)

    @property
    def reachable(self) -> bool:
        return not self.error


def check(answer: SuggestAnswer, given: SuggestInput) -> tuple[str, ...] | None:
    """The ids as they may be stored, or ``None``. Never raises."""
    ids = [str(product_id).strip() for product_id in answer.product_ids]
    known = {item.id for item in given.products}
    if len(set(ids)) != len(ids) or not set(ids) <= known or len(ids) > MAX_SHOWN:
        return None
    return tuple(ids)


def render(given: SuggestInput) -> str:
    """What the model reads: the shop's data inside untrusted tags, then the date."""
    data = {
        "shop": given.shop,
        "products": [
            {"id": item.id, "title": item.title, "category": item.category}
            for item in given.products
        ],
    }
    own = " It is the shop's own date, not a festival." if given.own else ""
    return (
        f"<untrusted_shop_data>\n{json.dumps(data, ensure_ascii=False, indent=1)}\n"
        f"</untrusted_shop_data>\n\n"
        f"The date: {given.name}, {given.day.strftime('%A')} {given.day.day} "
        f"{given.day.strftime('%B %Y')}.{own}\n"
        f"Choose 0 to {MAX_SHOWN} products."
    )


async def suggest(given: SuggestInput, *, llm: object, prompt: str) -> SuggestResult:
    """The suggestion for one date: with no call when code decides. Raises nothing."""
    if given.greeting_only:
        return SuggestResult(suggestion=Suggestion("greeting", "religious"))
    if not given.products:
        return SuggestResult(suggestion=Suggestion("greeting", "no_products"))
    question = render(given)
    raw: list[SuggestAnswer] = []
    for attempt in range(2):
        user = question
        if raw:
            user += (
                "\n\nYour last answer was refused by a check: it named an id that is not in the "
                f"list, the same id twice, or more than {MAX_SHOWN}. Answer again."
            )
        try:
            result = await llm.chat_structured(  # type: ignore[attr-defined]
                ModelRole.REASONER,
                ChatRequest(messages=[Message.system(prompt), Message.user(user)]),
                SuggestAnswer,
            )
        except Exception as exc:
            log.warning("grow_suggest_failed", error=type(exc).__name__, attempt=attempt)
            return SuggestResult(calls=attempt + 1, error=type(exc).__name__, raw=tuple(raw))
        raw.append(result.value)
        ids = check(result.value, given)
        if ids is not None:
            found = (
                Suggestion("products", "fit", ids) if ids else Suggestion("greeting", "none_fit")
            )
            return SuggestResult(suggestion=found, calls=attempt + 1, raw=tuple(raw))
        log.info("grow_suggest_refused", attempt=attempt)
    return SuggestResult(suggestion=Suggestion("none", "could_not"), calls=2, raw=tuple(raw))


__all__ = [
    "SuggestAnswer",
    "SuggestInput",
    "SuggestResult",
    "Suggestion",
    "check",
    "render",
    "suggest",
]
