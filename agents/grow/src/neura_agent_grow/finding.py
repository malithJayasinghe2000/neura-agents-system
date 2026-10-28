"""One exchange in, one checked gap, one wanted thing, or nothing out.

ADR-0064 §6 and §7, ADR-0068 §6. The night job hands the model one shopper
message and the reply it got, with the products that turn looked at, and asks
which **one** of three it is (R64): **a gap** (a fact the shop's pages could
state, which the reply could not give), **wanted** (a kind of product the shop
does not sell, and the reply said so), or **none**. One field carries the answer,
so one reply can never be both.

**Code decides what is stored, not the model** (Rule 3). The model reads shopper
text, and what it returns reaches the owner's page, so :func:`clean` refuses
anything that is not a short plain label and a short plain question: no link,
no email address, no long number, nothing the injection guard's rules match,
and no product the turn never looked at. A wanted thing gets the same checks,
and never a product at all: the shop does not sell it. A refused answer stores nothing; the
cost of a missed gap is a shorter list, and the cost of a stored trick would be
a line on the owner's page that a shopper wrote.

**Not every reply is sent** (R47, the owner's choice on cost): :func:`worth_asking`
is a free word check that runs first. A handover, a reply that says it cannot
confirm or does not have something (or does not carry or sell it, ADR-0068 §6),
and a reply not mostly in English are sent;
a reply that plainly gave its answer is not. The words it looks for are the ones
our own assistants are told to use (CARE's ``compose.md``: *say plainly what you
cannot confirm*), so a miss needs a half answer in unusual words.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from neura_agent_core.gaps import MAX_FACT_CHARS, MAX_QUESTION_CHARS
from neura_agent_core.guard.injection import scan
from neura_core import get_logger
from neura_llm import ChatRequest, Message, ModelRole

log = get_logger(__name__)

#: How much of each side of the exchange the model reads. A shopper message or a
#: reply longer than this is cut, never refused: the question is near the start,
#: and the rest would be paid for and not needed (R47).
MAX_TEXT_CHARS = 600
MAX_FACT_WORDS = 4
MAX_QUESTION_WORDS = 10

#: A label: lowercase letters, digits, spaces, ``'`` and ``-``. Nothing else.
_FACT = re.compile(r"^[a-z0-9][a-z0-9 '\-]*$")
#: A question: letters, digits, spaces, a few marks, ending with ``?``.
_QUESTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,'\-]*\?$")
#: Seven digits in a row, spaces allowed between them: a phone or order number.
_LONG_NUMBER = re.compile(r"(?:\d[\s-]?){7,}")
#: Words that never belong in a question about a product or a shop, and always
#: belong in an instruction to a model. A second net behind the injection guard,
#: whose rules are narrow on purpose (they must not refuse shoppers): *"ignore
#: your instructions"* passes them (G107).
_COMMAND_WORDS = frozenset(
    {
        "ignore",
        "disregard",
        "instruction",
        "instructions",
        "prompt",
        "prompts",
        "pretend",
        "override",
        "jailbreak",
        "admin",
    }
)


#: What a reply says when the shop's information did not have the answer. Any
#: match sends the reply to the model, which decides; a wrong match costs one call.
_UNSURE = re.compile(
    r"\b(?:"
    r"(?:can't|cannot|can not|unable to|not able to)\s+(?:confirm|say|tell|find|answer|see)"
    r"|(?:don't|do not|doesn't|does not|didn't|did not)\s+(?:have|know|say|state|specify|confirm|describe|mention|list|show|include|carry|sell|stock)"
    r"|not sure|unsure|unfortunately|i'm afraid"
    r"|no (?:information|info|details|data|mention)"
    r"|no products? match(?:ing|es)?"
    r"|(?:isn't|is not|aren't|are not|not)\s+(?:listed|mentioned|specified|stated|given|included)"
    r"|someone at (?:our|the) (?:store|shop)|contact (?:our|the) (?:store|shop)"
    r"|leave your email|pass (?:your|this|the) question"
    r")\b"
)
#: Short, very common English words. A reply with few of them is not mostly in
#: English (Singlish written in English letters, for one), so the word check
#: cannot read it and the model is asked instead.
_COMMON_ENGLISH = frozenset(
    [
        "a",
        "about",
        "also",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "here",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "more",
        "my",
        "no",
        "not",
        "of",
        "on",
        "only",
        "or",
        "our",
        "please",
        "price",
        "so",
        "sorry",
        "stock",
        "thank",
        "thanks",
        "that",
        "the",
        "there",
        "these",
        "this",
        "to",
        "us",
        "was",
        "we",
        "what",
        "which",
        "will",
        "with",
        "yes",
        "you",
        "your",
        "order",
    ]
)
#: Below this share of common words, a reply is treated as not English.
_MIN_COMMON_SHARE = 0.2


def _mostly_english(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return True
    if sum(ch.isascii() for ch in letters) < 0.8 * len(letters):
        return False
    words = [w for w in re.findall(r"[a-z']+", text.lower()) if not w.isdigit()]
    if not words:
        return True
    return sum(w in _COMMON_ENGLISH for w in words) >= _MIN_COMMON_SHARE * len(words)


def worth_asking(reply: str, *, handed_over: bool) -> bool:
    """Whether the model should read this reply at all. Free, and never raises.

    Leans to *yes*: a wrong *yes* costs one call, a wrong *no* loses a gap.
    """
    if handed_over:
        return True
    text = reply.replace("\u2019", "'").lower()
    return not _mostly_english(text) or bool(_UNSURE.search(text))


class Found(StrEnum):
    """Which one of three the exchange is (R64)."""

    GAP = "gap"
    WANTED = "wanted"
    NONE = "none"


class Finding(BaseModel):
    """What the model returns. Every field is checked by :func:`clean`."""

    model_config = ConfigDict(extra="ignore")

    found: Found = Field(
        description="gap: a fact the shop's pages could state; wanted: a kind of product "
        "the shop does not sell; none: anything else."
    )
    product_id: str | None = Field(
        default=None, description="For a gap, an id copied from the product list, or null."
    )
    topic: str | None = Field(default=None, description="One to four plain lowercase words.")
    question: str | None = Field(
        default=None, description="The shopper's question, short, ending with '?'."
    )


@dataclass(frozen=True, slots=True)
class Exchange:
    """One shopper message and the reply it got, as the night job read them."""

    shopper: str
    reply: str
    handed_over: bool
    #: The products this turn looked at, id to title.
    products: Mapping[str, str] = field(default_factory=dict)
    #: The labels already stored for each product (``""`` for the shop).
    known_facts: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: The things already found that the shop does not sell (ADR-0068 §6).
    known_wanted: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class CheckedGap:
    """A finding that passed every check: safe to store and to show."""

    product_id: str | None
    fact: str
    question: str


@dataclass(frozen=True, slots=True)
class CheckedWanted:
    """A thing the shop does not sell that passed every check (ADR-0068)."""

    label: str
    question: str


@dataclass(frozen=True, slots=True)
class FindResult:
    """The answer, and separately whether the model was reachable at all.

    An outage must not read as *no gap*: the scan would move past the reply and
    never look at it again.
    """

    gap: CheckedGap | None = None
    wanted: CheckedWanted | None = None
    error: str = ""
    #: What the model said before the checks, for the eval only: a product id it
    #: invented, or a planted question the checks refused, is worth measuring
    #: even though nothing unsafe was stored.
    raw: Finding | None = None

    @property
    def reachable(self) -> bool:
        return not self.error


def _plain(text: str) -> str:
    return " ".join(text.split())


def _unsafe(text: str) -> bool:
    lowered = text.lower()
    return (
        "@" in text
        or "http" in lowered
        or "www." in lowered
        or bool(_LONG_NUMBER.search(text))
        or bool(_COMMAND_WORDS & set(re.findall(r"[a-z]+", lowered)))
        or bool(scan(text).rules)
    )


def clean(finding: Finding, exchange: Exchange) -> CheckedGap | CheckedWanted | None:
    """The finding as it may be stored, or ``None``. Never raises.

    A gap and a wanted thing pass exactly the same checks on their label and
    question (ADR-0068 §6).
    """
    if finding.found is Found.NONE:
        return None
    topic = _plain(finding.topic or "").lower()
    question = _plain(finding.question or "")
    if not topic or not question:
        return None
    if (
        len(topic) > MAX_FACT_CHARS
        or len(topic.split()) > MAX_FACT_WORDS
        or not _FACT.match(topic)
        or _unsafe(topic)
    ):
        log.info("grow_gap_fact_refused", found=finding.found.value, length=len(topic))
        return None
    if (
        len(question) > MAX_QUESTION_CHARS
        or len(question.split()) > MAX_QUESTION_WORDS
        or not _QUESTION.match(question)
        or _unsafe(question)
    ):
        log.info("grow_gap_question_refused", found=finding.found.value, length=len(question))
        return None
    if finding.found is Found.WANTED:
        return CheckedWanted(label=topic, question=question)
    product_id = finding.product_id if finding.product_id in exchange.products else None
    return CheckedGap(product_id=product_id, fact=topic, question=question)


def render(exchange: Exchange) -> str:
    """The exchange as the model reads it, inside untrusted tags."""
    outcome = (
        "The assistant handed the shopper to the shop."
        if exchange.handed_over
        else "The assistant answered."
    )
    known = {key or "shop": list(values) for key, values in exchange.known_facts.items() if values}
    exchange_text = (
        f"Shopper: {exchange.shopper[:MAX_TEXT_CHARS]}\n\n"
        f"Assistant: {exchange.reply[:MAX_TEXT_CHARS]}"
    )
    return (
        f"<untrusted_exchange>\n{exchange_text}\n</untrusted_exchange>\n\n"
        f"{outcome}\n\n"
        f"Products this turn looked at (id: title): {json.dumps(dict(exchange.products))}\n"
        f"Topics already found (product id, or shop): {json.dumps(known)}\n"
        f"Things already asked for that the shop does not sell: "
        f"{json.dumps(list(exchange.known_wanted))}"
    )


async def find_gap(exchange: Exchange, *, llm: object, prompt: str) -> FindResult:
    """Ask the model, then check its answer. Raises nothing.

    ``llm`` is typed loosely as SELL's pairing types it: the job passes a metered
    wrapper and a test passes a stub.
    """
    try:
        result = await llm.chat_structured(  # type: ignore[attr-defined]
            ModelRole.ROUTER,
            ChatRequest(
                messages=[Message.system(prompt), Message.user(render(exchange))],
                temperature=0.0,
            ),
            Finding,
        )
    except Exception as exc:
        log.warning("grow_find_gap_failed", error=type(exc).__name__)
        return FindResult(error=type(exc).__name__)
    checked = clean(result.value, exchange)
    return FindResult(
        gap=checked if isinstance(checked, CheckedGap) else None,
        wanted=checked if isinstance(checked, CheckedWanted) else None,
        raw=result.value,
    )


__all__ = [
    "MAX_TEXT_CHARS",
    "CheckedGap",
    "CheckedWanted",
    "Exchange",
    "FindResult",
    "Finding",
    "Found",
    "clean",
    "find_gap",
    "render",
    "worth_asking",
]
