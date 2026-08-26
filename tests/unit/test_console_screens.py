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
from neura_api.routes.console_conversations import (
    _conversation_payload,
    _message_payload,
    _state,
)
from neura_core import ValidationError


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
        assert _message_payload(message(citations=cited))["citations"] == cited

    def test_a_timestamp_is_iso_or_null_and_never_a_guess(self) -> None:
        when = datetime.now(UTC)
        assert _message_payload(message(created_at=when))["created_at"] == when.isoformat()
        assert _message_payload(message())["created_at"] is None
