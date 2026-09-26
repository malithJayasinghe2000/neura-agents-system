"""Asking a model what *kinds* of product go with this one.

[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
§3 is this file. The model is shown one product's own text and asked for a short
list of **kinds** — ``wool socks``, ``shoe polish`` — and nothing else. It is
never given the catalogue, never asked to name a product, and has no tool, no
retrieval and no write.

**Why that shape is the safety argument and not a convenience.** The input is
merchant catalogue text, which [the glossary](../../../../../docs/glossary.md)
classifies as *untrusted content*: anybody with a merchant admin login can write
it. ADR-0040's defence was that there was no model to persuade, and that defence
is gone. What replaces it is structural — a persuaded model can return the
string ``Dry Bag Pro 2000``, and that string becomes a **search** against the
merchant's own shop, which finds nothing. An empty result is what ADR-0040 §4
already calls a correct outcome.

**Nothing here reaches a shopper as words.** A kind is a search term and is
never rendered; every visible string is the merchant's product data or
``select.heading_for``'s sentence.

**This file makes the call and does not decide when to make it.** Never on the
request path — that is ``orchestrate.py``'s rule and ADR-0045's first
non-negotiable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from neura_core import get_logger
from neura_domain import Product
from neura_llm import ChatRequest, Message, ModelRole

log = get_logger(__name__)

#: Kinds asked for per product. **A guess, and ADR-0045 §8 labels it one** — it
#: matches ``select.MAX_TERMS`` for no measured reason beyond spending the same
#: number of searches the word path spends.
MAX_KINDS = 3

#: Words allowed in one kind. The prompt asks for one to three; this is the
#: bound that holds when the prompt is ignored, which is the only kind of bound
#: worth having on untrusted input (AGENTS.md rule 3).
MAX_WORDS_PER_KIND = 3

#: Characters of merchant copy the model is shown. A description is arbitrary
#: text from a shop's admin, and an unbounded one is an unbounded prompt: a
#: merchant with a 40,000-character product page would otherwise decide what a
#: background job costs. Truncation loses the tail of a description, which is
#: where nothing that names the product lives.
MAX_TEXT_CHARS = 2000

#: Word characters only, same expression and same reasoning as
#: ``select._WORD``: a kind becomes a *search term*, and digits, punctuation and
#: markup in one find the product they were copied from, or nothing at all.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


class PairedKinds(BaseModel):
    """What the model is allowed to return. One field, and it is a list of
    strings — there is no field in which to name a product, an id, a price or a
    sentence for a shopper, because a schema is a bound a prompt is not."""

    kinds: list[str] = Field(
        default_factory=list,
        description="Kinds of product that go with this one. Empty is a correct answer.",
    )


def clean_kinds(raw: list[str]) -> list[str]:
    """Bound what a model returned before it becomes a search.

    Every rule here is applied to output that may have been written by a product
    description rather than by the prompt, so none of them trusts the model to
    have followed an instruction:

    * **Words only.** Rebuilt from word characters, which drops markup, URLs,
      control characters, measurements and anything else a search engine would
      match to one product or to none.
    * **At most :data:`MAX_WORDS_PER_KIND` words**, lowercased.
    * **Distinct, in the order the model gave them**, capped at
      :data:`MAX_KINDS`. The order is kept because it is the model's own
      ranking and is the only ranking this path has — unlike the word path,
      where ``select.rank_by_rarity`` *measures* one.
    """
    kept: dict[str, None] = {}

    for candidate in raw:
        words = [match.group().lower() for match in _WORD.finditer(str(candidate))]
        if not words:
            continue
        if (kind := " ".join(words[:MAX_WORDS_PER_KIND])) not in kept:
            kept[kind] = None
        if len(kept) == MAX_KINDS:
            break

    return list(kept)


def render(product: Product) -> str:
    """The one product the model is shown, delimited as untrusted.

    The same tagging as ``route.md``'s ``<untrusted_customer_message>`` and for
    the same reason: the boundary between *this is the material* and *this is
    the instruction* has to be visible in the text, because it is invisible in
    the model.
    """
    text = f"{product.title}\n\n{product.description or ''}".strip()
    return f"<untrusted_product_text>\n{text[:MAX_TEXT_CHARS]}\n</untrusted_product_text>"


@dataclass(frozen=True, slots=True)
class KindsResult:
    """What the model said, and — separately — whether it was reachable at all.

    **The two are not the same answer and must not be returned as one.** A model
    that read a product and honestly found nothing to pair with it returns no
    kinds; so does a provider that is down. Collapsing them into an empty list
    would mean an outage is written into the cache as *"this product pairs with
    nothing"* and stays there, which is the shape of
    [E6](../../../../../docs/open-questions.md) — a dead server reported as a
    result — arriving in a table instead of a report.

    ``error`` is a type name, never the exception's text: a provider's message
    can carry a URL or a key fragment, and this string is logged and stored.
    """

    kinds: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def reachable(self) -> bool:
        return not self.error


async def kinds_for(product: Product, *, llm: object, prompt: str) -> KindsResult:
    """What goes with this product, as kinds. Raises nothing.

    A provider that is down, a refusal, a response that will not parse — none of
    them raises here, because the caller is a background job and the queue's
    retry ladder is a better place to decide what a failure is worth than a
    stack unwinding through a cart page's cousin. What the caller gets instead
    is a :class:`KindsResult` that says which happened.

    ``llm`` is typed loosely for the reason ``Runtime.llm`` is: the caller
    passes a metered wrapper, and a test passes a stub.
    """
    try:
        result = await llm.chat_structured(  # type: ignore[attr-defined]
            ModelRole.REASONER,
            ChatRequest(
                messages=[Message.system(prompt), Message.user(render(product))],
                temperature=0.0,
            ),
            PairedKinds,
        )
    except Exception as exc:
        log.warning(
            "pairing_kinds_failed",
            product_id=product.external_id,
            error=type(exc).__name__,
        )
        return KindsResult(error=type(exc).__name__)

    kinds = clean_kinds(result.value.kinds)

    log.info(
        "pairing_kinds",
        product_id=product.external_id,
        # What the model asked for, after cleaning — the answer to "why was I
        # shown a frock?" one layer above the term counts the word path logs.
        kinds=kinds,
        returned=len(result.value.kinds),
        attempts=getattr(result, "attempts", 1),
    )
    return KindsResult(kinds=kinds)


__all__ = [
    "MAX_KINDS",
    "MAX_TEXT_CHARS",
    "MAX_WORDS_PER_KIND",
    "KindsResult",
    "PairedKinds",
    "clean_kinds",
    "kinds_for",
    "render",
]
