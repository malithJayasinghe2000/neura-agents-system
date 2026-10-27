"""G74, R35: the assistants offer only what a "yes" really leads to.

Nobody called *a colleague* exists. Since ADR-0062 a shopper who takes the offer
reaches the handover, whose first words are *"Leave your email so our store can
answer you."* So every offer says that **someone at our store can answer**, and
never that the AI passes anything on or that a person will come.

The three fixed texts are the owner's words (R35), word for word. The
instructions say the same thing in one phrase, and the fact checkers know that
phrase, so the offer is never flagged as a claim. None of the shopper's texts
may trip the promise detector, or every reply that carries one is handed over.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from neura_agent_care.prompts import load_prompts as care_prompts
from neura_agent_core.guard.promises import find_promises
from neura_agent_sell.prompts import load_prompts as sell_prompts

REPO = Path(__file__).resolve().parents[2]
CARE_SRC = REPO / "agents/care/src/neura_agent_care"
SELL_SRC = REPO / "agents/sell/src/neura_agent_sell"

#: What G74 found untrue: an offer of a person who does not exist, or of an
#: action the reply cannot take.
UNTRUE = ("colleague", "pass you over", "pass you to", "passing it on", "pass them to a")

#: The one phrase the instructions use.
OFFER = "offer to pass their question to someone at our store"

CARE_DECLINE = "If you'd like someone at our store to answer it anyway, just say so."
SELL_ASK_STORE = "Or just say so and someone at our store can answer you; they may know more."


def _flat(text: str) -> str:
    """A prompt file wraps its lines; the shopper reads one paragraph."""
    return " ".join(text.split())


@pytest.mark.parametrize(
    "path",
    [
        *sorted((CARE_SRC / "prompts").glob("*.md")),
        *sorted((SELL_SRC / "prompts").glob("*.md")),
        CARE_SRC / "tools/orders.py",
        CARE_SRC / "tools/policies.py",
    ],
    ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}/{p.name}",
)
def test_no_instruction_or_fixed_text_offers_a_colleague(path: Path) -> None:
    text = _flat(path.read_text()).lower()
    assert not [w for w in UNTRUE if w in text]


def test_cares_decline_says_the_owners_words() -> None:
    assert _flat(care_prompts()["decline"]).endswith(CARE_DECLINE)


def test_sells_no_match_says_the_owners_words() -> None:
    text = _flat(sell_prompts()["no_match"])
    assert text.endswith(
        "describe what you need differently and I'll look again. " + SELL_ASK_STORE
    )


def test_sells_no_match_with_a_need_says_the_owners_words() -> None:
    assert _flat(sell_prompts()["no_match_constraint"]).endswith(SELL_ASK_STORE)


@pytest.mark.parametrize(
    ("agent", "name"),
    [("care", "decline"), ("sell", "no_match"), ("sell", "no_match_constraint")],
)
def test_the_fixed_texts_promise_nothing(agent: str, name: str) -> None:
    prompts = care_prompts() if agent == "care" else sell_prompts()
    assert find_promises(_flat(prompts[name])) == []


def test_care_is_told_one_offer_everywhere() -> None:
    compose = _flat(care_prompts()["compose"])
    assert compose.count(OFFER) >= 3
    for path in (CARE_SRC / "tools/orders.py", CARE_SRC / "tools/policies.py"):
        assert "pass their question to someone at our store" in _flat(path.read_text())


def test_sell_ends_a_recommendation_by_offering_only_to_narrow_it_down() -> None:
    """R35, A: a shopper choosing a tea needs no person."""
    compose = _flat(sell_prompts()["compose"])
    assert "End by offering to narrow it down." in compose
    assert "someone at our store" not in compose


@pytest.mark.parametrize("prompts", [care_prompts, sell_prompts], ids=["care", "sell"])
def test_the_fact_checkers_know_the_offer(prompts: Callable[[], dict[str, str]]) -> None:
    assert "offers to pass the shopper's question to someone at the store" in _flat(
        prompts()["verify"]
    )


def test_cares_router_hands_over_a_yes_to_the_offer() -> None:
    """G109: after the decline's offer, "yes please" was declined again on Gemini.

    A short reply means nothing alone, so the router reads it against the offer
    it answers: taking up the offer of a person is a request for one.
    """
    route = _flat(care_prompts()["route"])
    assert "accepts an offer of someone at our store" in route
    assert '"yes please" → `needs_person`' in route
