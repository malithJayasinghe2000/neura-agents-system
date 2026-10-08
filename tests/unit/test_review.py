"""The review queue's judgements, without a database. Console screen 3.

Everything here is about **what the screen is told when there is nothing to
show**, because that is where a grading queue goes wrong. The database-backed
half — that a person reaches only their own tenant's rows, that a revoked
membership stops working immediately — is in
`tests/integration/test_console_review.py`, where RLS is real.

`docs/console.md §3.2` states three rules for this screen and two of them are
assertions about absence:

* evidence must be shown, and a citation with nothing behind it must say so
  rather than render an empty panel;
* a withheld turn must *look* withheld — including the ones the agent declined
  to answer, which are the interesting ones (ADR-0020);
* and nothing may be sampled.

The fourth is `CLAUDE.md §4`: no number that was not measured. A cost of zero is
the trap, and it has its own class below.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from neura_agent_core.review import (
    IN_CATALOGUE,
    SOURCE_GONE,
    TOOL_NOT_RECORDED,
    Evidence,
    ReviewItem,
    _evidence_for,
    no_draft_reason,
)
from neura_agent_core.shadow import ShadowTurn, ShadowVerdict
from neura_api.routes.console_review import (
    _cost_payload,
    _item_payload,
    _scorecard_payload,
)


def turn(**overrides: object) -> ShadowTurn:
    """One shadowed turn, with only the fields a test cares about set."""
    fields: dict[str, object] = {
        "tenant_id": "tn_test",
        "id": "msg_shadow",
        "conversation_id": "cnv_1",
        "message_id": "msg_1",
        "agent_key": "care",
        "mode": "shadow",
        "state": "resolved",
        "draft": "Your order shipped on Tuesday.",
    }
    fields.update(overrides)
    return ShadowTurn(**fields)  # type: ignore[arg-type]


class TestEvidenceIsShownOrExplained:
    """`console.md §3.2`: a grader who cannot see what the agent worked from is
    grading fluency."""

    def test_a_cited_document_carries_the_merchants_own_text(self) -> None:
        evidence = _evidence_for(
            turn(citations=[{"type": "policy", "id": "returns"}]),
            {("policy", "returns"): ("Returns accepted within 30 days.", False)},
        )
        assert evidence == [
            Evidence(
                kind="document",
                type="policy",
                id="returns",
                excerpt="Returns accepted within 30 days.",
                truncated=False,
                available=True,
            )
        ]

    def test_a_tool_is_named_and_says_its_result_is_not_here(self) -> None:
        """Not an omission. The record a tool returned is the shopper's own data
        and lives in the audit log under its retention policy."""
        [piece] = _evidence_for(turn(citations=[{"type": "tool", "id": "get_order"}]), {})
        assert piece.kind == "tool"
        assert piece.available is False
        assert piece.reason == TOOL_NOT_RECORDED

    def test_a_source_that_is_no_longer_indexed_says_so(self) -> None:
        """The panel must not simply be blank — that is indistinguishable from a
        bug, which is the whole of ADR-0020's argument."""
        [piece] = _evidence_for(turn(citations=[{"type": "faq", "id": "sizing"}]), {})
        assert piece.available is False
        assert piece.reason == SOURCE_GONE

    def test_a_product_still_in_the_catalogue_is_not_called_deleted(self) -> None:
        """G39: SELL cites the products it read live from the shop. On a shop with
        no search index every one of them read "may have been deleted"."""
        [piece] = _evidence_for(
            turn(citations=[{"type": "product", "id": "4"}]),
            {},
            {"4": "Ceylon Black Tea BOPF 400g"},
        )
        assert piece.reason == f"Ceylon Black Tea BOPF 400g — {IN_CATALOGUE}"
        assert "deleted" not in piece.reason
        assert piece.available is False, "the text the assistant saw is still not shown"

    def test_a_product_gone_from_the_catalogue_too_is_still_called_gone(self) -> None:
        [piece] = _evidence_for(turn(citations=[{"type": "product", "id": "9"}]), {}, {"4": "Tea"})
        assert piece.reason == SOURCE_GONE

    def test_only_products_are_looked_up_in_the_catalogue(self) -> None:
        [piece] = _evidence_for(turn(citations=[{"type": "policy", "id": "4"}]), {}, {"4": "Tea"})
        assert piece.reason == SOURCE_GONE

    def test_every_citation_produces_a_row_even_when_nothing_backs_it(self) -> None:
        """Dropping the unresolvable ones would tell a grader the agent worked
        from less than it did."""
        evidence = _evidence_for(
            turn(
                citations=[
                    {"type": "policy", "id": "returns"},
                    {"type": "faq", "id": "gone"},
                    {"type": "tool", "id": "get_order"},
                ]
            ),
            {("policy", "returns"): ("text", False)},
        )
        assert len(evidence) == 3
        assert [piece.available for piece in evidence] == [True, False, False]

    def test_truncation_is_reported_rather_than_silent(self) -> None:
        [piece] = _evidence_for(
            turn(citations=[{"type": "policy", "id": "returns"}]),
            {("policy", "returns"): ("half a policy", True)},
        )
        assert piece.truncated is True

    def test_a_malformed_citation_is_skipped_rather_than_rendered_empty(self) -> None:
        assert _evidence_for(turn(citations=[{"type": "", "id": ""}, {}]), {}) == []


class TestAWithheldTurnSaysSo:
    """ADR-0020, pointed at the merchant instead of the shopper.

    A turn the agent declined must appear in the queue *and* explain itself. An
    empty draft with no words is the silence ADR-0020 §4 forbids.
    """

    def test_every_row_is_marked_withheld(self) -> None:
        """True on every row, because a `shadow_turns` row *is* a reply nobody
        saw. A field rather than something the screen infers — inference is how
        a client ends up rendering nothing."""
        payload = _item_payload(ReviewItem(turn=turn()))
        assert payload["withheld"] is True

    def test_an_escalated_turn_with_no_draft_explains_itself(self) -> None:
        reason = no_draft_reason(turn(draft="", escalated=True))
        assert "handed this to a person" in reason

    def test_a_draft_discarded_by_verify_quotes_the_reason(self) -> None:
        """A failed grounding check is a decision made *about* the agent, and
        conflating it with an escalation hides the one that says it was wrong."""
        reason = no_draft_reason(
            turn(draft="", grounded=False, verify_reason="claimed a refund policy")
        )
        assert "grounding check" in reason
        assert "claimed a refund policy" in reason

    def test_a_blocked_turn_names_the_guard(self) -> None:
        reason = no_draft_reason(turn(draft="", state="blocked"))
        assert "guard" in reason

    def test_an_unexplained_empty_draft_still_produces_words(self) -> None:
        """The fallback case. Whatever happened, the card is never blank."""
        assert no_draft_reason(turn(draft="", state="resolved")).strip()

    def test_no_draft_reason_is_empty_exactly_when_there_is_a_draft(self) -> None:
        assert _item_payload(ReviewItem(turn=turn()))["no_draft_reason"] == ""
        assert _item_payload(ReviewItem(turn=turn(draft="   ")))["no_draft_reason"]

    def test_whitespace_is_not_a_draft(self) -> None:
        assert ReviewItem(turn=turn(draft="  \n ")).has_draft is False


class TestTheQuestionIsCarried:
    """A reply without the question it answers is not gradeable at all, and the
    `shadow_turns` row *looks* complete without it."""

    def test_the_question_travels_with_the_turn(self) -> None:
        payload = _item_payload(
            ReviewItem(turn=turn(), question="where is my order?", asked_at=datetime.now(UTC))
        )
        assert payload["question"]["text"] == "where is my order?"
        assert payload["question"]["recorded"] is True

    def test_a_deleted_message_is_distinguishable_from_an_empty_one(self) -> None:
        """A retention policy can delete the transcript and leave a graded row
        behind. "We no longer have it" and "they said nothing" are different
        sentences on the screen."""
        payload = _item_payload(ReviewItem(turn=turn(), question="", question_recorded=False))
        assert payload["question"]["recorded"] is False


class TestNoInventedNumbers:
    """`CLAUDE.md §4`, in the one place a merchant reads figures."""

    def test_a_zero_cost_is_not_reported_as_a_measurement(self) -> None:
        """`PriceTable.cost` returns zero for a **local** model and zero for a
        cloud model with no configured price. Those are different facts, and
        nothing at this layer can tell them apart — so the flag says the figure
        means nothing rather than the screen printing "$0.00"."""
        assert _cost_payload(Decimal("0")) == {"usd": "0", "measured": False}

    def test_a_real_cost_is_reported_as_one(self) -> None:
        assert _cost_payload(Decimal("0.004212")) == {"usd": "0.004212", "measured": True}

    def test_an_ungraded_queue_has_no_agreement_rate(self) -> None:
        """`null`, not `0.0`. An unreviewed queue is not a queue that failed
        review, and dividing by recorded turns would make the figure improve
        every time the agent ran."""
        from neura_agent_core.shadow import Scorecard

        payload = _scorecard_payload(Scorecard(total=12))
        assert payload["agreement_rate"] is None
        assert payload["harm_free"] is None
        assert payload["ungraded"] == 12

    def test_every_rate_arrives_with_its_denominator(self) -> None:
        from neura_agent_core.shadow import Scorecard

        payload = _scorecard_payload(Scorecard(total=4, graded=2, agree=2))
        assert payload["agreement_rate"] == 1.0
        assert payload["graded"] == 2, "100% over two graded turns must not look like 100% over 200"

    def test_harm_is_a_boolean_and_never_a_rate(self) -> None:
        """There is no acceptable percentage of harmful answers about a
        shopper's money, so the go-live question is "any?"."""
        from neura_agent_core.shadow import Scorecard

        card = Scorecard(total=50, graded=50, agree=49, would_have_harmed=1)
        payload = _scorecard_payload(card)
        assert payload["harm_free"] is False
        assert payload["verdicts"]["would_have_harmed"] == 1


class TestThePayloadCarriesNoCredential:
    """`console.md §6.6`: no credential and no API key in any response body."""

    def test_the_row_exposes_no_key_and_no_tenant_secret(self) -> None:
        payload = _item_payload(
            ReviewItem(
                turn=turn(verdict=ShadowVerdict.AGREE, reviewed_by="usr_1"),
                question="where is my order?",
            )
        )
        rendered = repr(payload)
        assert "fn_sk_" not in rendered
        assert "fn_pk_" not in rendered
        # The tenant id is not in the payload either: the caller already named
        # the shop in the URL and had it checked, so repeating it would only add
        # a value a client might start trusting.
        assert "tenant_id" not in payload
