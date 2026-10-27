"""ADR-0062 §10: the email a handed-over shopper types, checked by the route itself.

Checked in code rather than by the request model, because FastAPI's own
validation error repeats what was sent (``input``), and the address must never
be in an error answer. These are the rules; the route is
``tests/integration/test_api_postgres.py``'s ``TestHandoverEmail``.
"""

from __future__ import annotations

import pytest

from neura_api.routes.handover_email import MAX_EMAIL_CHARS, shopper_email


@pytest.mark.parametrize(
    ("typed", "kept"),
    [
        ("saman@example.com", "saman@example.com"),
        ("  saman.perera@example.com  ", "saman.perera@example.com"),
        ("Saman@Example.COM", "Saman@example.com"),
        ("nadeesha+tea@example.co.uk", "nadeesha+tea@example.co.uk"),
    ],
)
def test_a_real_address_is_kept_as_typed(typed: str, kept: str) -> None:
    """Trimmed, and the domain written the standard way; the name part as typed."""
    assert shopper_email(typed) == kept


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "saman.perera@",
        "saman",
        "@example.com",
        "saman@example",
        "saman@@example.com",
        "saman example@example.com",
        "saman@example.com\nBcc: other@example.com",
    ],
)
def test_anything_else_is_refused(typed: str) -> None:
    assert shopper_email(typed) is None


def test_an_address_longer_than_email_allows_is_refused() -> None:
    long = "a" * 64 + "@" + ("b" * 60 + ".") * 4 + "com"
    assert len(long) > MAX_EMAIL_CHARS
    assert shopper_email(long) is None
