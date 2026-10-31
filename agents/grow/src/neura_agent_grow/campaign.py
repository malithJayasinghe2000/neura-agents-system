"""One kept date in, one checked campaign plan (or a refusal) out. ADR-0072 §5, §6.

The night run hands the model the date, the shop's name, up to 100 of its
in-stock products (id, title, category) and **labels and counts only** of what
its shoppers asked: the things on *Shoppers asked for* and the topics on
*Missing from your pages*. Never a shopper's question, never a conversation id
(ADR-0072 §5).

**Code decides what is stored, not the model** (Rule 3). The model reads the
shop's catalogue and labels derived from shoppers' words, and what it writes is
published by the shop under its own name, so :func:`check` refuses an answer
that:

* names a product id it was not given, or the wrong number of products;
* names a fact it was not given, or more than three;
* holds a price or an offer (a ``%``, a currency sign or code, a number followed
  by *off*, *free*, *half price*): the place for one is **[your offer]**;
* holds a claim from a fixed list (*organic*, *cures*, *guaranteed*, *No. 1* and
  the like), **in English only** (R88);
* holds a link, a phone number, an email address or an ``@`` handle;
* states a count of shoppers, customers or orders (the page shows the real one);
* holds a bracket other than **[your offer]**, or anything the injection
  guard's rules match;
* has a field empty or too long.

A refused answer is asked for **once more**, told which rule it broke; refused
again, the plan *could not be made* (ADR-0072 §5). An unreachable model is not
a refusal: it is reported, so the night run stops and the queue retries.

**What the page shows comes from our data and code**: the products' names,
photos and prices from the catalogue, the counts from the stored rows, the
schedule's days from :func:`neura_agent_core.calendar.post_days`. The model
chooses products and facts **by id**, and writes the idea and the drafts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from neura_agent_core.calendar import TEXT_FIELDS, post_days
from neura_agent_core.guard.injection import scan
from neura_core import get_logger
from neura_llm import ChatRequest, Message, ModelRole

log = get_logger(__name__)

#: The most products the model is shown (ADR-0072 §5); a bigger catalogue is cut.
MAX_PRODUCTS = 100
#: The most of each kind of fact the model is shown, most asked first.
MAX_FACTS = 10
#: The most facts a plan may put under *Act on this first*.
MAX_ACT_ON = 3
#: How many products a plan shows (R84: 2 or 3), fewer only when the shop has fewer.
MIN_PRODUCTS, MAX_SHOWN = 2, 3
#: The one placeholder a draft may hold (ADR-0072 §5).
OFFER = "[your offer]"

#: Each text field's limit, in characters.
LIMITS: dict[str, int] = {
    "theme": 60,
    "idea": 600,
    "teaser": 400,
    "launch": 400,
    "last_chance": 400,
    "email_subject": 100,
    "email_body": 1500,
    "banner": 100,
}

#: Claims a small shop cannot stand behind without proof (ADR-0072 §6). Read in
#: English only (R88): why Sinhala and Tamil drafts wait.
CLAIM_WORDS = (
    "organic",
    "cure",
    "cures",
    "cured",
    "heal",
    "heals",
    "healing",
    "treats",
    "treatment",
    "guaranteed",
    "guarantee",
    "clinically",
    "clinical",
    "certified",
    "proven",
    "miracle",
    "doctor",
    "doctors",
    "immunity",
    "detox",
    "no. 1",
    "no 1",
    "number one",
    "#1",
    "best in sri lanka",
    "best in the world",
)
_CLAIM = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(word) for word in CLAIM_WORDS) + r")(?![a-z0-9])"
)
#: A price or an offer, in any language: a percentage, a currency, *off*, *free*.
_PRICE = re.compile(
    r"%|\bper ?cent\b|[$€£¥₹₨฿₩]"
    r"|\b(?:rs|lkr|usd|eur|gbp|inr|aud|cad|sgd|aed|jpy|myr|rupees?|dollars?)\b"
    r"|\d[\d,.]*\s*off\b|\bfree\b|\bhalf[ -](?:price|off)\b|\bbogo\b"
    r"|\bbuy (?:one|1) get (?:one|1)\b"
)
#: A link, an email address, an ``@`` handle, or a phone number.
_CONTACT = re.compile(
    r"@|https?:|www\.|\b[a-z0-9-]+\.(?:com|lk|net|org|io|co|shop|store|info|biz)\b"
    r"|(?:\d[\s-]?){7,}"
)
#: A count the model must not state: the page shows the real one.
_COUNT = re.compile(r"\b\d[\d,]*\s+(?:shoppers?|customers?|people|persons|buyers?|orders?)\b")
_BRACKETS = re.compile(r"\[[^\]]*\]")


#: What the model is told on its second try, by refusal: fixed words from code.
#: The keys are also the codes stored as a failed plan's ``failure``.
RETRY_REASONS: dict[str, str] = {
    "product": "it named a product id that is not in the list, or the wrong number of products",
    "fact": "act_on named a ref that is not in the lists, or more than 3",
    "price": (
        "a text held a price, a discount, a percentage, a currency or the word free; "
        f"write {OFFER} where an offer would go"
    ),
    "claim": "a text held a word from the list of claims you must never write",
    "contact": "a text held a link, a web address, a phone number, an email address or an @",
    "count": "a text held a number of shoppers, customers, people or orders",
    "placeholder": f"a text held brackets other than {OFFER}",
    "guard": "a text held words that read as instructions to a computer",
    "length": "a field was empty or too long",
}


@dataclass(frozen=True, slots=True)
class CatalogueItem:
    """A product the model may choose, by its id."""

    id: str
    title: str
    category: str = ""


@dataclass(frozen=True, slots=True)
class Fact:
    """A label and a count from the shop's own data, never a shopper's words."""

    ref: str
    #: ``wanted`` (*Shoppers asked for*) or ``gap`` (*Missing from your pages*).
    kind: str
    label: str
    shoppers: int
    #: For a gap about a product: which one. ``None`` for the shop or a wanted thing.
    product_id: str | None = None
    product_title: str = ""


@dataclass(frozen=True, slots=True)
class PlanInput:
    """Everything the model is given for one date."""

    shop: str
    name: str
    day: date
    products: Sequence[CatalogueItem] = ()
    facts: Sequence[Fact] = ()
    #: The catalogue had more in-stock products than :data:`MAX_PRODUCTS`.
    cut: bool = False

    @property
    def shown(self) -> tuple[int, int]:
        """How many products the plan must choose: at least, at most."""
        have = len(self.products)
        return min(MIN_PRODUCTS, have), min(MAX_SHOWN, have)


class PlanAnswer(BaseModel):
    """What the model returns. Every field is checked by :func:`check`."""

    model_config = ConfigDict(extra="ignore")

    theme: str = Field(description="A short name for the campaign.")
    idea: str = Field(description="Two to four plain sentences.")
    product_ids: list[str] = Field(description="Ids copied from the product list.")
    act_on: list[str] = Field(default_factory=list, description="Refs such as w1 or g2.")
    teaser: str
    launch: str
    last_chance: str
    email_subject: str
    email_body: str
    banner: str


@dataclass(frozen=True, slots=True)
class CheckedPlan:
    """An answer that passed every check: what is stored and shown."""

    theme: str
    idea: str
    products: tuple[str, ...]
    act_on: tuple[Fact, ...]
    texts: dict[str, str]
    cut: bool = False

    def stored(self) -> dict[str, Any]:
        """The plan as ``calendar_plans.answer`` holds it: labels and counts only."""
        return {
            "theme": self.theme,
            "idea": self.idea,
            "products": list(self.products),
            "act_on": [
                {
                    "kind": fact.kind,
                    "label": fact.label,
                    "shoppers": fact.shoppers,
                    "product_id": fact.product_id,
                }
                for fact in self.act_on
            ],
            "texts": dict(self.texts),
            "catalogue_cut": self.cut,
        }


@dataclass(frozen=True, slots=True)
class PlanResult:
    """The checked plan, or why there is none; and how many calls it took."""

    plan: CheckedPlan | None = None
    #: The refusal of each answer that failed the checks, in order.
    refusals: tuple[str, ...] = ()
    calls: int = 0
    #: Set when the model could not be reached: a retry, not a result.
    error: str = ""
    #: What the model said before the checks, for the eval only.
    raw: tuple[PlanAnswer, ...] = field(default_factory=tuple)

    @property
    def reachable(self) -> bool:
        return not self.error


def _plain(text: str) -> str:
    """Spaces tidied, line breaks kept (an email has paragraphs)."""
    lines = [" ".join(line.split()) for line in text.replace("\r", "").split("\n")]
    joined = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", joined)


def text_refusal(text: str) -> str | None:
    """Which rule one text breaks, or ``None``. Never raises."""
    lowered = text.lower().replace("\u2019", "'")
    if _PRICE.search(lowered):
        return "price"
    if _CONTACT.search(lowered):
        return "contact"
    if _CLAIM.search(lowered):
        return "claim"
    if _COUNT.search(lowered):
        return "count"
    if any(found.lower() != OFFER for found in _BRACKETS.findall(text)) or any(
        mark in text for mark in "<>{}"
    ):
        return "placeholder"
    if scan(text.replace(OFFER, "")).rules:
        return "guard"
    return None


def claim_in(answer: PlanAnswer) -> str:
    """The first claim word an answer holds, from :data:`CLAIM_WORDS`, or ``""``.

    Named on the retry, so the model knows which word to leave out. It is a word
    of our own list, never the model's or a shopper's text.
    """
    for name in ("theme", "idea", *TEXT_FIELDS):
        found = _CLAIM.search(str(getattr(answer, name) or "").lower())
        if found:
            return found.group(0)
    return ""


def check(answer: PlanAnswer, given: PlanInput) -> CheckedPlan | str:
    """The answer as it may be stored, or the refusal's code. Never raises."""
    fields = {"theme": answer.theme, "idea": answer.idea}
    fields.update({name: getattr(answer, name) for name in TEXT_FIELDS})
    cleaned = {name: _plain(value or "") for name, value in fields.items()}
    for name, value in cleaned.items():
        if not value or len(value) > LIMITS[name]:
            return "length"
    for value in cleaned.values():
        if (refusal := text_refusal(value)) is not None:
            return refusal

    ids = [str(product_id).strip() for product_id in answer.product_ids]
    known = {item.id for item in given.products}
    least, most = given.shown
    if len(set(ids)) != len(ids) or not set(ids) <= known or not least <= len(ids) <= most:
        return "product"
    facts = {fact.ref: fact for fact in given.facts}
    refs = [str(ref).strip() for ref in answer.act_on]
    if len(set(refs)) != len(refs) or not set(refs) <= facts.keys() or len(refs) > MAX_ACT_ON:
        return "fact"

    return CheckedPlan(
        theme=cleaned["theme"],
        idea=cleaned["idea"],
        products=tuple(ids),
        act_on=tuple(facts[ref] for ref in refs),
        texts={name: cleaned[name] for name in TEXT_FIELDS},
        cut=given.cut,
    )


def render(given: PlanInput) -> str:
    """What the model reads: the shop's data inside untrusted tags, then the date."""
    posts = post_days(given.day)
    least, most = given.shown
    data = {
        "shop": given.shop,
        "products": [
            {"id": item.id, "title": item.title, "category": item.category}
            for item in given.products
        ],
        "shoppers_asked_for_what_the_shop_does_not_sell": [
            {"ref": f.ref, "label": f.label, "shoppers": f.shoppers}
            for f in given.facts
            if f.kind == "wanted"
        ],
        "questions_the_shops_pages_do_not_answer": [
            {
                "ref": f.ref,
                "topic": f.label,
                "product": f.product_title or "the shop in general",
                "shoppers": f.shoppers,
            }
            for f in given.facts
            if f.kind == "gap"
        ],
    }
    cut = (
        f" The shop has more products in stock than these {len(given.products)}."
        if given.cut
        else ""
    )
    return (
        f"<untrusted_shop_data>\n{json.dumps(data, ensure_ascii=False, indent=1)}\n"
        f"</untrusted_shop_data>\n\n"
        f"The date: {given.name}, {_long(given.day)}.{cut}\n"
        f"The teaser post goes out on {_long(posts['teaser'])}, the launch post and the "
        f"email on {_long(posts['launch'])}, the last chance post on "
        f"{_long(posts['last_chance'])}. The banner runs from {_long(posts['launch'])} "
        f"to the day before the date.\n"
        f"Choose {least if least == most else f'{least} or {most}'} products."
    )


def _long(day: date) -> str:
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"


async def write_plan(given: PlanInput, *, llm: object, prompt: str) -> PlanResult:
    """Ask the model, check the answer, and ask once more if it was refused.

    ``llm`` is typed loosely as the night check types it: the job passes a
    metered wrapper and a test passes a stub. Raises nothing.
    """
    question = render(given)
    refusals: list[str] = []
    raw: list[PlanAnswer] = []
    for attempt in range(2):
        user = question
        if refusals:
            reason = RETRY_REASONS[refusals[-1]]
            if refusals[-1] == "claim" and (word := claim_in(raw[-1])):
                reason += f' ("{word}"; leave it out in every form, also as an ordinary word)'
            user += (
                f"\n\nYour last answer was refused by a check: {reason}. "
                "Write the whole answer again and follow every rule."
            )
        try:
            result = await llm.chat_structured(  # type: ignore[attr-defined]
                ModelRole.REASONER,
                ChatRequest(messages=[Message.system(prompt), Message.user(user)]),
                PlanAnswer,
            )
        except Exception as exc:
            log.warning("grow_plan_failed", error=type(exc).__name__, attempt=attempt)
            return PlanResult(
                refusals=tuple(refusals),
                calls=attempt + 1,
                error=type(exc).__name__,
                raw=tuple(raw),
            )
        raw.append(result.value)
        checked = check(result.value, given)
        if isinstance(checked, CheckedPlan):
            return PlanResult(
                plan=checked, refusals=tuple(refusals), calls=attempt + 1, raw=tuple(raw)
            )
        log.info("grow_plan_refused", refusal=checked, attempt=attempt)
        refusals.append(checked)
    return PlanResult(refusals=tuple(refusals), calls=2, raw=tuple(raw))


__all__ = [
    "CLAIM_WORDS",
    "LIMITS",
    "MAX_ACT_ON",
    "MAX_FACTS",
    "MAX_PRODUCTS",
    "OFFER",
    "RETRY_REASONS",
    "CatalogueItem",
    "CheckedPlan",
    "Fact",
    "PlanAnswer",
    "PlanInput",
    "PlanResult",
    "check",
    "claim_in",
    "render",
    "text_refusal",
    "write_plan",
]
