"""What the console's screens decide, without a database.

`test_review.py` covers screen 3's judgements; this file covers the rest. The
database-backed half of each — that a person reaches only their own tenant's
rows — is in `tests/integration/`, because RLS cannot be tested without
PostgreSQL and a policy nobody exercised is a policy nobody has.

Everything here is a **refusal to soften something**: a filter that must fail
rather than be ignored, five states that must not become three, a zero that must
not be printed as money.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neura_agent_core.conversations import Conversation, ConversationState, Message, Role
from neura_agent_core.shadow import ShadowTurn, ShadowVerdict
from neura_api.routes.console_conversations import (
    _conversation_payload,
    _held_payload,
    _message_payload,
    _state,
)
from neura_api.routes.console_shop import COUNTED, _checkpoint_payload, _notes
from neura_api.routes.console_usage import PERIODS, _caveats, _totals_payload
from neura_commerce.identity import EntityType
from neura_core import ValidationError
from neura_core.tenancy.usage import UsageTotals


class TestTheStateFilter:
    def test_no_filter_means_no_filter(self) -> None:
        assert _state(None) is None
        assert _state("") is None

    @pytest.mark.parametrize("value", [s.value for s in ConversationState])
    def test_every_real_state_is_accepted(self, value: str) -> None:
        """Parametrised over the enum rather than a hand-written list, so a sixth
        state added later is covered the day it exists rather than the day
        somebody remembers this file."""
        assert _state(value) is ConversationState(value)

    def test_an_unknown_state_is_refused_rather_than_ignored(self) -> None:
        """A silently dropped filter returns *everything* while looking like a
        filtered list — which is how a merchant concludes they have no
        escalations. 400, not a shrug."""
        with pytest.raises(ValidationError):
            _state("nonsense")

    def test_the_refusal_says_what_was_expected(self) -> None:
        """A 400 that does not name the valid values makes the caller guess."""
        with pytest.raises(ValidationError) as raised:
            _state("resolvedd")
        assert "escalated" in str(raised.value.details["expected"])


def conversation(**overrides: object) -> Conversation:
    fields: dict[str, object] = {
        "tenant_id": "tn_test",
        "id": "cnv_1",
        "agent_key": "care",
        "state": ConversationState.RESOLVED,
    }
    fields.update(overrides)
    return Conversation(**fields)  # type: ignore[arg-type]


class TestTheConversationRow:
    def test_the_list_ships_no_message_content(self) -> None:
        """Listing a hundred conversations must not ship a hundred transcripts.
        A merchant's dashboard that wants one asks for it by id."""
        payload = _conversation_payload(conversation())
        assert "messages" not in payload
        assert "content" not in payload

    def test_the_five_states_survive_the_payload(self) -> None:
        """`blocked` and `escalated` are both refusals costing wildly different
        things (ADR-0012), and `shadowed` is neither. Any collapsing here would
        be invisible on the wire and obvious only to a confused merchant."""
        for state in ConversationState:
            assert _conversation_payload(conversation(state=state))["state"] == state.value

    def test_a_shadowed_conversation_is_not_reported_as_resolved(self) -> None:
        """The one that would inflate the number this product is sold on."""
        assert (
            _conversation_payload(conversation(state=ConversationState.SHADOWED))["state"]
            == "shadowed"
        )

    def test_no_tenant_id_is_echoed_back(self) -> None:
        """The caller named the shop in the URL and had it checked against their
        membership. Repeating it adds a value a client might start trusting."""
        assert "tenant_id" not in _conversation_payload(conversation())


def message(**overrides: object) -> Message:
    fields: dict[str, object] = {
        "role": Role.AGENT,
        "content": "Yes — within 30 days.",
        "sequence": 2,
        "id": "msg_2",
    }
    fields.update(overrides)
    return Message(**fields)  # type: ignore[arg-type]


class TestTheMessage:
    def test_the_reply_carries_its_outcome_and_the_question_does_not(self) -> None:
        """`state` belongs to the reply. A question had no outcome."""
        assert _message_payload(message(state=ConversationState.RESOLVED))["state"] == "resolved"
        assert _message_payload(message(role=Role.SHOPPER, sequence=1))["state"] is None

    def test_content_is_returned_exactly_as_stored(self) -> None:
        """Tokenised — `[EMAIL_1]`, not an address (security-model.md §6.2).

        Nothing in the console redacts and nothing rehydrates. The second is not
        possible: the vault is per-turn and never persisted. The first would be a
        silent second opinion about a decision the guard already made.

        This pins **what is true today** while `console.md §3.3` still promises
        the merchant unredacted PII. The day somebody resolves that, this test
        goes red and the change gets an ADR rather than happening quietly.
        """
        stored = "ship to [ADDRESS_1], email [EMAIL_1]"
        assert _message_payload(message(content=stored))["content"] == stored

    def test_citations_travel_with_the_reply(self) -> None:
        cited = [{"type": "policy", "id": "returns"}]
        assert _message_payload(message(citations=cited))["citations"] == [
            {"type": "policy", "id": "returns", "name": None}
        ]

    def test_a_citation_carries_its_catalogue_name_by_type_and_id(self) -> None:
        """The pair is the key: a product and a policy can share an id."""
        cited = [
            {"type": "policy", "id": "7"},
            {"type": "product", "id": "7"},
            {"type": "tool", "id": "search_products"},
        ]
        names = {("policy", "7"): "Return Policy"}
        payload = _message_payload(message(citations=cited), names)["citations"]
        assert [c["name"] for c in payload] == ["Return Policy", None, None]

    def test_a_timestamp_is_iso_or_null_and_never_a_guess(self) -> None:
        when = datetime.now(UTC)
        assert _message_payload(message(created_at=when))["created_at"] == when.isoformat()
        assert _message_payload(message())["created_at"] is None


def held(**overrides: object) -> ShadowTurn:
    fields: dict[str, object] = {
        "tenant_id": "tn_test",
        "conversation_id": "cnv_1",
        "message_id": "msg_question",
        "agent_key": "care",
        "mode": "shadow",
        "state": "resolved",
        "draft": "Yes — within 30 days.",
        "id": "msg_draft",
    }
    fields.update(overrides)
    return ShadowTurn(**fields)  # type: ignore[arg-type]


class TestAHeldDraftOnTheChatPage:
    """2026-09-28: the chat page shows each held draft under its question."""

    def test_it_names_the_question_it_answers(self) -> None:
        payload = _held_payload(held())
        assert payload["message_id"] == "msg_question"
        assert payload["id"] == "msg_draft"

    def test_a_draft_needs_no_reason(self) -> None:
        assert _held_payload(held())["no_draft_reason"] == ""

    def test_no_draft_always_says_why(self) -> None:
        """ADR-0020: an empty bubble reads as a bug."""
        assert (
            "handed this to a person"
            in _held_payload(held(draft="", escalated=True))["no_draft_reason"]
        )
        assert _held_payload(held(draft="  "))["no_draft_reason"]

    def test_ungraded_is_null_and_not_a_verdict(self) -> None:
        payload = _held_payload(held())
        assert payload["verdict"] is None
        assert payload["reviewed_at"] is None

    def test_a_grade_carries_its_verdict_and_who(self) -> None:
        when = datetime.now(UTC)
        payload = _held_payload(
            held(verdict=ShadowVerdict.AGREE, reviewed_by="usr_1", reviewed_at=when)
        )
        assert payload["verdict"] == "agree"
        assert payload["reviewed_by"] == "usr_1"
        assert payload["reviewed_at"] == when.isoformat()

    def test_the_evidence_and_the_cost_stay_in_review(self) -> None:
        """Grading happens in Review, beside the evidence (console.md §3.2)."""
        payload = _held_payload(held())
        assert not {"evidence", "cost", "verify", "citations"} & payload.keys()


class TestTheShopScreenSaysWhatItKnows:
    def test_a_sync_that_never_finished_is_null_and_not_a_date(self) -> None:
        """ "Never finished" and "finished at the epoch" are different facts and
        only one should make a merchant worry. Nothing defaults this."""
        payload = _checkpoint_payload(
            _checkpoint(entity_type=EntityType.PRODUCT, completed_at=None)
        )
        assert payload["completed_at"] is None

    def test_the_opaque_cursor_is_never_in_the_payload(self) -> None:
        """A cursor is opaque by design (api-design.md §5). Whether a crawl is
        part-way through is the fact a merchant needs; the value is not, and it
        is the sort of field that gets pasted into a support ticket and goes
        stale."""
        payload = _checkpoint_payload(_checkpoint(cursor="an-encoded-cursor"))
        assert "cursor" not in payload
        assert payload["in_progress"] is True

    def test_nothing_in_progress_when_there_is_no_cursor(self) -> None:
        assert _checkpoint_payload(_checkpoint(cursor=None))["in_progress"] is False

    def test_orders_and_customers_are_deliberately_not_counted(self) -> None:
        """They are looked up live through the shop and never synced
        (commerce-integration.md), so counting them would report zero and read
        as a broken sync rather than as a design decision."""
        assert EntityType.ORDER not in COUNTED
        assert EntityType.CUSTOMER not in COUNTED
        assert EntityType.PRODUCT in COUNTED

    def test_variants_are_not_counted(self) -> None:
        """Sizes and colours live inside a product's document, so a variant
        count always read 0 beside a catalogue that plainly had them."""
        assert EntityType.VARIANT not in COUNTED


class TestTheShopScreensSentences:
    """The sentences under the catalogue's figures (`console.md §3.4`), from the
    server so they can change when what they describe does."""

    def test_it_always_says_nothing_syncs_by_itself(self) -> None:
        [note] = _notes(products=0, searchable=0)
        assert note["key"] == "no_schedule"
        assert "nothing syncs by itself yet" in note["text"]

    def test_the_index_line_says_what_is_missing(self) -> None:
        index = _notes(products=38, searchable=29)[1]
        assert index == {
            "key": "index",
            "text": (
                "Search by meaning covers 29 of 38 products — the other 9 are not in it "
                "yet, so the AI can't find them that way."
            ),
        }

    def test_one_missing_product_is_said_in_the_singular(self) -> None:
        assert _notes(products=5, searchable=4)[1]["text"].endswith(
            "the other 1 is not in it yet, so the AI can't find it that way."
        )

    def test_a_complete_index_says_so_without_a_shortfall(self) -> None:
        assert _notes(products=38, searchable=38)[1]["text"] == (
            "Search by meaning covers all 38 products."
        )

    def test_no_products_means_no_index_line(self) -> None:
        """Nothing to cover, so no sentence about covering it."""
        assert [n["key"] for n in _notes(products=0, searchable=0)] == ["no_schedule"]


class TestTheUsageScreenInventsNothing:
    """`console.md §5` and `CLAUDE.md §4`, at the layer that builds the payload."""

    def test_the_payload_carries_counts_and_not_one_ratio(self) -> None:
        payload = _totals_payload(UsageTotals(tenant_id="tn_1", conversations=41, escalations=2))
        assert payload["conversations"] == 41
        assert payload["escalations"] == 2
        assert not any(key.endswith("_rate") for key in payload)

    def test_a_zero_cost_is_never_a_measurement(self) -> None:
        """Zero is what a local model records *and* what a hosted model with no
        configured price records (`neura_llm.pricing`). Nothing below this layer
        can tell them apart."""
        assert _totals_payload(UsageTotals(tenant_id="tn_1"))["cost"]["measured"] is False

    def test_a_real_cost_is_reported_as_one(self) -> None:
        from decimal import Decimal

        payload = _totals_payload(UsageTotals(tenant_id="tn_1", cost_usd=Decimal("1.42")))
        assert payload["cost"] == {"usd": "1.42", "measured": True}

    def test_shadow_mode_is_the_first_thing_said(self) -> None:
        """True numbers describing work no shopper ever saw is the most
        misleading page this console could produce. It leads."""
        caveats = _caveats(UsageTotals(tenant_id="tn_1", conversations=41), "shadow")
        assert caveats[0]["key"] == "practice_mode"
        assert "practice mode" in caveats[0]["text"]

    def test_a_live_shop_claims_nothing_about_withholding(self) -> None:
        caveats = _caveats(UsageTotals(tenant_id="tn_1", conversations=41), "live")
        assert not any(caveat["key"] == "practice_mode" for caveat in caveats)
        assert not any("practice mode" in caveat["text"] for caveat in caveats)

    def test_the_escalation_count_is_stated_with_its_denominator_and_disclaimed(
        self,
    ) -> None:
        """Both halves matter. A merchant reading "2 of 41" will otherwise do the
        division and call the answer a deflection rate — which `CLAUDE.md §4`
        lists as unknown."""
        [caveat] = [
            c["text"]
            for c in _caveats(
                UsageTotals(tenant_id="tn_1", conversations=41, escalations=2), "live"
            )
            if c["key"] == "handed_to_a_person"
        ]
        assert "2 of 41 conversations" in caveat
        assert "not a deflection rate" in caveat

    def test_a_shop_with_no_conversations_makes_no_claim_about_them(self) -> None:
        """Nothing recorded means nothing to disclaim. A caveat that is always
        present is a caveat the reader learns to skip."""
        caveats = _caveats(UsageTotals(tenant_id="tn_1"), "live")
        assert not any(caveat["key"] == "handed_to_a_person" for caveat in caveats)

    def test_everything_ever_recorded_is_not_a_number_of_days(self) -> None:
        assert PERIODS["all"] is None

    def test_the_periods_offered_are_the_periods_accepted(self) -> None:
        """The screen's tabs and the endpoint's whitelist are the same dict, so a
        tab cannot come to offer a window the API refuses."""
        assert set(PERIODS) == {"today", "7d", "30d", "all"}


def _checkpoint(**overrides: object):
    """A `SyncCheckpoint` with only what a test cares about set."""
    from neura_commerce.sync.state import SyncCheckpoint, SyncKey

    key = SyncKey(
        tenant_id="tn_1",
        platform="fixture",
        entity_type=overrides.pop("entity_type", EntityType.PRODUCT),  # type: ignore[arg-type]
    )
    fields: dict[str, object] = {"key": key, "last_run_count": 7}
    fields.update(overrides)
    if isinstance(fields.get("cursor"), str):
        from neura_commerce.pagination import Cursor

        fields["cursor"] = Cursor(state={"page": 1})
    return SyncCheckpoint(**fields)  # type: ignore[arg-type]
