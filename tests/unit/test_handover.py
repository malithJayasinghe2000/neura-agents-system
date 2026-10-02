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
