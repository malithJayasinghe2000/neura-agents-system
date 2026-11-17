"""Ask the owner first (ADR-0078): the suggestion, the greeting, and no stock words.

**The suggestion** (§1) is ids only, checked in code; Vesak and Poson and a shop
with nothing in stock are decided with no model call. **A greeting** (§4) has
every check of a plan, plus no selling words and no ``[your offer]``. **No plan
says anything about stock** (§5, G130).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from neura_agent_core.calendar import (
    ASK_DAYS_BEFORE,
    SUGGESTED_BY_KEY,
    Occurrence,
    Plan,
    PlanKind,
    PlanState,
)
from neura_agent_grow.campaign import (
    OFFER,
    CatalogueItem,
    CheckedPlan,
    GreetingAnswer,
    PlanInput,
    check_greeting,
    render_greeting,
    text_refusal,
    write_plan,
)
from neura_agent_grow.prompts import load_prompts
from neura_agent_grow.suggest import SuggestAnswer, SuggestInput, check, render, suggest

PRODUCTS = (
    CatalogueItem("4", "Ceylon Black Tea BOPF 400g", "Black tea"),
    CatalogueItem("9", "Tea Gift Box, 6 Teas", "Gift sets"),
)
GIVEN = SuggestInput(
    shop="Ceylon Harvester", name="Christmas", day=date(2026, 12, 25), products=PRODUCTS
)


class _Model:
    """Answers with the given answers in turn; can be unreachable."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.seen: list[Any] = []

    async def chat_structured(self, role: Any, request: Any, schema: Any) -> Any:
        self.seen.append((request, schema))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer

        class _Result:
            value = answer

        return _Result()


class TestTheSuggestion:
    async def test_products_that_fit_are_suggested(self) -> None:
        result = await suggest(GIVEN, llm=_Model(SuggestAnswer(product_ids=["9"])), prompt="s")
        assert result.suggestion is not None
        assert result.suggestion.stored() == {
            "kind": "products",
            "reason": "fit",
            "products": ["9"],
        }

    async def test_none_fits_is_a_greeting_not_a_forced_product(self) -> None:
        """G131: the AI may answer none."""
        result = await suggest(GIVEN, llm=_Model(SuggestAnswer(product_ids=[])), prompt="s")
        assert result.suggestion is not None
        assert (result.suggestion.kind, result.suggestion.reason) == ("greeting", "none_fit")

    @pytest.mark.parametrize("key", ["vesak", "poson"])
    async def test_vesak_and_poson_are_a_greeting_with_no_call(self, key: str) -> None:
        assert SUGGESTED_BY_KEY[key].greeting_only
        model = _Model()
        given = SuggestInput(
            shop="x", name="Vesak", day=date(2027, 5, 20), products=PRODUCTS, greeting_only=True
        )
        result = await suggest(given, llm=model, prompt="s")
        assert result.suggestion is not None and result.suggestion.reason == "religious"
        assert (result.calls, model.seen) == (0, [])

    async def test_no_product_in_stock_is_a_greeting_with_no_call(self) -> None:
        given = SuggestInput(shop="x", name="Christmas", day=date(2026, 12, 25))
        result = await suggest(given, llm=_Model(), prompt="s")
        assert result.suggestion is not None and result.suggestion.reason == "no_products"

    @pytest.mark.parametrize("ids", [["999"], ["4", "4"], ["4", "9", "4"], ["1", "2", "3", "4"]])
    def test_an_id_not_given_repeated_or_too_many_is_refused(self, ids: list[str]) -> None:
        assert check(SuggestAnswer(product_ids=ids), GIVEN) is None

    async def test_refused_twice_suggests_nothing_and_the_owner_chooses(self) -> None:
        bad = SuggestAnswer(product_ids=["999"])
        result = await suggest(GIVEN, llm=_Model(bad, bad), prompt="s")
        assert result.suggestion is not None
        assert (result.suggestion.kind, result.calls) == ("none", 2)

    async def test_an_outage_is_a_retry_not_a_suggestion(self) -> None:
        result = await suggest(GIVEN, llm=_Model(RuntimeError("down")), prompt="s")
        assert not result.reachable and result.suggestion is None

    def test_the_catalogue_is_inside_the_untrusted_block(self) -> None:
        text = render(GIVEN)
        assert text.index("Tea Gift Box") < text.index("</untrusted_shop_data>")
        assert "Christmas" in text.split("</untrusted_shop_data>")[1]


def _greeting(**overrides: Any) -> GreetingAnswer:
    values = {
        "theme": "A peaceful Vesak",
        "greeting": "Ceylon Harvester wishes you and your family a peaceful and blessed Vesak.",
        "banner": "Wishing you a peaceful Vesak",
    }
    values.update(overrides)
    return GreetingAnswer(**values)


class TestAGreeting:
    def test_a_good_greeting_is_stored_with_no_products(self) -> None:
        checked = check_greeting(_greeting())
        assert isinstance(checked, CheckedPlan)
        assert checked.products == () and set(checked.texts) == {"greeting", "banner"}

    @pytest.mark.parametrize(
        "text",
        [
            "A Vesak sale at Ceylon Harvester",
            "Buy our tea this Vesak",
            "Shop now for Vesak",
            "Vesak deals all week",
            f"A peaceful Vesak and {OFFER}",
        ],
    )
    def test_selling_is_refused(self, text: str) -> None:
        assert check_greeting(_greeting(greeting=text)) == "selling"

    def test_a_plan_check_applies_too(self) -> None:
        assert check_greeting(_greeting(banner="Call 0771234567 this Vesak")) == "contact"

    def test_the_greeting_is_given_the_shop_and_the_date_only(self) -> None:
        given = PlanInput(
            shop="Ceylon Harvester",
            name="Vesak",
            day=date(2027, 5, 20),
            products=PRODUCTS,
            greeting=True,
        )
        text = render_greeting(given)
        assert "Ceylon Harvester" in text and "Vesak" in text and "Tea Gift Box" not in text

    async def test_a_greeting_plan_uses_its_own_schema(self) -> None:
        model = _Model(_greeting())
        given = PlanInput(shop="x", name="Vesak", day=date(2027, 5, 20), greeting=True)
        result = await write_plan(given, llm=model, prompt="g")
        assert result.plan is not None and model.seen[0][1] is GreetingAnswer


class TestNoStockWords:
    """G130: a sold-out product posted as available, or manufactured urgency."""

    @pytest.mark.parametrize(
        "text",
        [
            "Ceylon Black Tea, available now",
            "Back in stock for Avurudu",
            "Only a few left!",
            "Only 3 boxes left",
            "Our gift box is selling fast",
            "Limited stock, while stocks last",
            "Hurry, it is almost gone",
            "Sold out last year, so come early",
            "A limited edition tin",
            "Freshly restocked for Avurudu",
        ],
    )
    def test_is_refused(self, text: str) -> None:
        assert text_refusal(text) == "stock"

    @pytest.mark.parametrize(
        "text",
        [
            "Stock up on tea for Avurudu",
            "Last chance before Avurudu",
            "A tea for every home",
            "Payday is the time to restock your kitchen pantry",
            "Just two days left until payday!",
            "Only 3 more days left",
        ],
    )
    def test_ordinary_words_pass(self, text: str) -> None:
        assert text_refusal(text) is None

    def test_both_prompts_say_it(self) -> None:
        prompts = load_prompts()
        assert "**No stock.**" in prompts["plan_campaign"]
        assert "**No stock.**" in prompts["write_greeting"]


class TestThePlanState:
    def _plan(self, **fields: Any) -> Plan:
        fields.setdefault("answer", None)
        return Plan(id="p", date_key="s:vesak", day=date(2027, 5, 20), name="Vesak", **fields)

    def test_a_suggestion_waits_for_the_owner(self) -> None:
        assert self._plan(suggestion={"kind": "greeting"}).state is PlanState.CHOOSE

    def test_skipped(self) -> None:
        plan = self._plan(suggestion={"kind": "greeting"}, skipped_at=date(2027, 4, 22))  # type: ignore[arg-type]
        assert plan.state is PlanState.SKIPPED

    def test_a_greeting_has_its_own_texts(self) -> None:
        plan = self._plan(
            answer={"texts": {"greeting": "Peace", "banner": "Vesak"}}, plan_kind=PlanKind.GREETING
        )
        assert plan.state is PlanState.READY and plan.texts() == {
            "greeting": "Peace",
            "banner": "Vesak",
        }

    def test_the_ai_suggests_four_weeks_before(self) -> None:
        occurrence = Occurrence(
            date_key="s:vesak", name="Vesak", year=2027, day=date(2027, 5, 20), key="vesak"
        )
        assert ASK_DAYS_BEFORE == 28 and occurrence.plan_day == date(2027, 4, 22)
        assert occurrence.greeting_only
