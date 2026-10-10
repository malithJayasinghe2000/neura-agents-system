"""ADR-0058 §4: the invite email, word for word.

Plain text, short, as the sign-in email is. It names who invited, the shop, the
role and what the role can do (the People screen's cards), says the link works
once and until when, and that nothing happens if it is ignored. No long dash, a
house rule for what people read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neura_api.routes.console_people import INVITE_SUBJECT, ROLE_LINES, invite_body
from neura_core.identity import Role

URL = "https://console.example/auth/invite?shop=tn_1&token=abc"
UNTIL = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)


def test_the_whole_email_for_a_developer() -> None:
    assert invite_body(
        inviter="Pat Owner", shop="Dispatch Test Shop", role="developer", url=URL, until=UNTIL
    ) == (
        "Hello,\n\n"
        "Pat Owner invited you to Dispatch Test Shop's dashboard on FiveNeurals, as Developer.\n\n"
        "As the Developer you can open Shop connection and Help: you connect the shop and make "
        "its secrets. You never see shoppers' chats.\n\n"
        "Use the link below to join:\n\n"
        f"{URL}\n\n"
        "It works once, until October 17, 2026.\n\n"
        "If you did not expect this email, you can ignore it. "
        "Nothing happens unless the link is used.\n"
    )


def test_the_subject_names_the_shop() -> None:
    assert INVITE_SUBJECT.format(shop="Dispatch Test Shop") == (
        "You're invited to Dispatch Test Shop on FiveNeurals"
    )


@pytest.mark.parametrize("role", [r.value for r in Role])
def test_every_role_has_its_sentence_and_no_long_dash(role: str) -> None:
    body = invite_body(inviter="Pat", shop="A Shop", role=role, url=URL, until=UNTIL)
    assert ROLE_LINES[role] in body
    assert "—" not in body
    assert "—" not in ROLE_LINES[role]
