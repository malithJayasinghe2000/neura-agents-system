"""ADR-0057 §7: what a shopper who is not signed in reads about an order.

Fixed text, never the AI's, in the owner's words (accepted 2026-10-08). Made in
one place (`neura_core.tenancy.sign_in_message`) from the shop's own contact
details; the graph's own sign-in step says the no-details form, so a path that
skips the turn service (an eval) says the same words.
"""

from __future__ import annotations

import pytest

from neura_agent_core.graph.nodes.sign_in import DEFAULT_MESSAGE
from neura_core.tenancy import (
    PASS_EXPIRED_MESSAGE,
    SIGN_IN_WITHOUT_DETAILS,
    TenantConfig,
    sign_in_message,
)


def test_the_words_are_the_owners() -> None:
    assert SIGN_IN_WITHOUT_DETAILS == (
        "Please sign in to your account so I can help with your orders."
    )
    assert PASS_EXPIRED_MESSAGE == (
        "Your sign-in on this page has timed out. Please reload the page and ask again."
    )


@pytest.mark.parametrize(
    ("email", "phone", "expected"),
    [
        (
            "hello@yourshop.example",
            "+94 11 234 5678",
            "Please sign in to your account so I can help with your orders. "
            "Or contact our store: hello@yourshop.example, +94 11 234 5678.",
        ),
        (
            "hello@yourshop.example",
            None,
            "Please sign in to your account so I can help with your orders. "
            "Or contact our store: hello@yourshop.example.",
        ),
        (
            None,
            "+94 11 234 5678",
            "Please sign in to your account so I can help with your orders. "
            "Or contact our store: +94 11 234 5678.",
        ),
        (None, None, "Please sign in to your account so I can help with your orders."),
    ],
)
def test_it_names_what_the_owner_set(email: str | None, phone: str | None, expected: str) -> None:
    assert sign_in_message(TenantConfig(contact_email=email, contact_phone=phone)) == expected


def test_the_graph_says_the_no_details_sentence() -> None:
    assert DEFAULT_MESSAGE == SIGN_IN_WITHOUT_DETAILS
