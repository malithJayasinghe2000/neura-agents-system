"""ADR-0055: a handover tells the shopper how to contact the shop, and promises nothing.

The sentence a handed-over shopper reads is made in one place
(`neura_core.tenancy.handover_message`) from the shop's own contact details. The
engine's fallback and CARE's prompt file say the no-details sentence, so a path
that skips the turn service (an eval) cannot say the old one (G44).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neura_agent_core.graph.nodes.escalate import DEFAULT_MESSAGE
from neura_core.tenancy import HANDOVER_WITHOUT_DETAILS, TenantConfig, handover_message

REPO = Path(__file__).resolve().parents[2]

#: What G44 found untrue: nobody comes, and nothing is passed on to anyone.
PROMISES = ("colleague", "member of the team", "passing you", "explain it again", "everything we")


@pytest.mark.parametrize(
    ("email", "phone", "expected"),
    [
        (
            "hello@yourshop.example",
            "+94 11 234 5678",
            "I can't help with this here. Please contact our store: "
            "hello@yourshop.example, +94 11 234 5678.",
        ),
        (
            "hello@yourshop.example",
            None,
            "I can't help with this here. Please contact our store: hello@yourshop.example.",
        ),
        (
            None,
            "+94 11 234 5678",
            "I can't help with this here. Please contact our store: +94 11 234 5678.",
        ),
        (None, None, "I can't help with this here. Please contact our store."),
    ],
)
def test_the_sentence_names_what_the_owner_set(
    email: str | None, phone: str | None, expected: str
) -> None:
    config = TenantConfig(contact_email=email, contact_phone=phone)
    assert handover_message(config) == expected
    assert not any(promise in expected.lower() for promise in PROMISES)


def test_with_nothing_set_it_is_the_no_details_sentence() -> None:
    assert handover_message(TenantConfig()) == HANDOVER_WITHOUT_DETAILS


def test_the_engines_fallback_promises_nothing() -> None:
    """The shared escalate node, which SELL uses as it is."""
    assert DEFAULT_MESSAGE == HANDOVER_WITHOUT_DETAILS


def test_cares_own_handover_text_promises_nothing() -> None:
    text = (REPO / "agents/care/src/neura_agent_care/prompts/escalation_message.md").read_text()
    assert text.strip() == HANDOVER_WITHOUT_DETAILS


def test_a_shop_without_details_loads_as_before() -> None:
    """Every shop saved before this ADR has neither key."""
    config = TenantConfig.model_validate({"mode": "live"})
    assert config.contact_email is None
    assert config.contact_phone is None


# ── ADR-0062: a handed-over shopper may leave an email (R31's words) ─────────

from neura_core.tenancy import (  # noqa: E402 - kept beside the tests that use them
    HANDOVER_ASK,
    HANDOVER_WITH_STORE,
    WRONG_EMAIL,
    email_thanks,
    handover_ask_message,
    handover_with_store_message,
)

#: ADR-0062 §5: *can*, not *will*: NEURA cannot promise that the shop answers.
PROMISES_AN_ANSWER = (" will ", "we'll", "someone will", "get back to you")


class TestTheWordsAShopperReadsAtAHandover:
    """The owner's words, approved 2026-10-11 (R31). Fixed text, never the AI's."""

    CONTACT = TenantConfig(contact_email="hello@yourshop.example", contact_phone="+94 11 234 5678")

    def test_the_ask_with_the_shops_details(self) -> None:
        assert handover_ask_message(self.CONTACT) == (
            "I can't answer this here. Leave your email so our store can answer you.\n"
            "Or contact our store: hello@yourshop.example, +94 11 234 5678."
        )

    def test_the_ask_with_one_detail(self) -> None:
        config = TenantConfig(contact_phone="+94 11 234 5678")
        assert handover_ask_message(config) == (
            "I can't answer this here. Leave your email so our store can answer you.\n"
            "Or contact our store: +94 11 234 5678."
        )

    def test_the_ask_with_no_details_has_no_contact_line(self) -> None:
        """ADR-0055 §3's rule: the line is left out when nothing is set."""
        assert handover_ask_message(TenantConfig()) == HANDOVER_ASK
        assert (
            HANDOVER_ASK
            == "I can't answer this here. Leave your email so our store can answer you."
        )

    def test_a_signed_in_shopper_is_told_the_question_is_with_the_store(self) -> None:
        assert handover_with_store_message(self.CONTACT) == (
            "I can't answer this here. Your question is with our store, and they can answer you "
            "by email.\nOr contact our store: hello@yourshop.example, +94 11 234 5678."
        )
        assert handover_with_store_message(TenantConfig()) == HANDOVER_WITH_STORE

    def test_after_send_the_shopper_reads_their_own_address(self) -> None:
        assert email_thanks("saman@example.com") == (
            "Thanks. Your question is with our store, and they can answer you at saman@example.com."
        )

    def test_a_wrong_address(self) -> None:
        assert WRONG_EMAIL == "Please check your email address."

    def test_no_sentence_promises_an_answer_or_a_person(self) -> None:
        sentences = [
            handover_ask_message(self.CONTACT),
            handover_with_store_message(self.CONTACT),
            email_thanks("saman@example.com"),
        ]
        for sentence in sentences:
            lowered = f" {sentence.lower()} "
            assert not any(promise in lowered for promise in PROMISES_AN_ANSWER), sentence
            assert not any(promise in lowered for promise in PROMISES), sentence


class TestTheEmailTheTeamSends:
    """ADR-0062 §7, approved with the mockup (board 53): what *Answer by email*
    fills the team member's own email app with. Never the AI's draft."""

    def test_the_subject_the_question_and_the_shops_name(self) -> None:
        from neura_core.tenancy import answer_email

        subject, body = answer_email("Ceylon Harvester", "Can I return an opened pack?")
        assert subject == "Your question to Ceylon Harvester"
        assert body == (
            "Hello,\n\nYou asked us in the chat on our website:\n"
            "“Can I return an opened pack?”\n\n\n\nCeylon Harvester"
        )

    def test_a_chat_with_no_question_still_has_the_gap_and_the_name(self) -> None:
        from neura_core.tenancy import answer_email

        assert answer_email("Ceylon Harvester", None) == (
            "Your question to Ceylon Harvester",
            "Hello,\n\n\n\n\nCeylon Harvester",
        )
