"""The first human in the system. ADR-0026.

These cover the parts that need no database: the session cookie, and the rules
about what a sign-in must never reveal. The database-backed half — token
redemption, membership isolation between two tenants — is in
`tests/integration/test_identity.py`, because RLS cannot be tested without
PostgreSQL and a policy nobody exercised is a policy nobody has.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neura_core.email import Mailer, SendResult
from neura_core.identity import COOKIE_NAME, SESSION_TTL, issue, verify

SECRET = "a-test-signing-secret"
USER = "usr_01TESTTESTTESTTESTTESTTEST"


class TestSessionCookie:
    def test_a_signed_session_verifies(self) -> None:
        assert verify(issue(USER, SECRET), SECRET).user_id == USER  # type: ignore[union-attr]

    def test_a_tampered_cookie_is_rejected(self) -> None:
        cookie = issue(USER, SECRET)
        assert verify(cookie[:-2] + "xx", SECRET) is None

    def test_a_cookie_signed_with_another_secret_is_rejected(self) -> None:
        """The whole security of the session is this line."""
        assert verify(issue(USER, SECRET), "a-different-secret") is None

    def test_an_expired_cookie_is_rejected(self) -> None:
        long_ago = datetime.now(UTC) - SESSION_TTL - timedelta(days=1)
        assert verify(issue(USER, SECRET, now=long_ago), SECRET) is None

    def test_a_forged_payload_cannot_be_swapped_in(self) -> None:
        """The attack the signature exists to stop: rewrite `sub`, keep the tag."""
        import base64
        import json

        body, _, signature = issue(USER, SECRET).rpartition(".")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        payload["sub"] = "usr_somebody_else"
        forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

        assert verify(f"{forged}.{signature}", SECRET) is None

    def test_rubbish_is_rejected_rather_than_raising(self) -> None:
        for value in ("", "no-dot", "....", "a.b", "!!!.???"):
            assert verify(value, SECRET) is None

    def test_a_session_cannot_be_issued_for_nobody(self) -> None:
        """An empty user id would sign a valid cookie for no one."""
        with pytest.raises(ValueError, match="no user id"):
            issue("", SECRET)

    def test_a_session_cannot_be_signed_with_an_empty_secret(self) -> None:
        """The failure mode is a cookie anybody can forge, and it looks fine."""
        with pytest.raises(ValueError, match="empty secret"):
            issue(USER, "")

    def test_the_cookie_name_keeps_its_host_prefix(self) -> None:
        """`__Host-` is enforced by the browser: Secure, path /, no Domain.

        It is what stops a sibling subdomain setting or overwriting the session
        cookie, which is a real attack and the only part of this the browser
        will defend for us.
        """
        assert COOKIE_NAME.startswith("__Host-")

    def test_the_cookie_carries_the_person_and_no_authority(self) -> None:
        """ADR-0026 §3. A tenant or role in here would be unrevocable."""
        import base64
        import json

        body, _, _sig = issue(USER, SECRET).rpartition(".")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))

        assert set(payload) == {"v", "sub", "iat", "exp"}
        assert "tenant" not in str(payload).lower()
        assert "role" not in str(payload).lower()


class TestMailer:
    def test_an_unconfigured_mailer_skips_rather_than_raising(self) -> None:
        """Every developer machine and every CI run is in this state.

        A mailer that raised here would make `make check` need a mail server.
        """
        from neura_core.config import Settings

        result = Mailer(Settings(SMTP_HOST="")).send(to="a@b.test", subject="s", body="b")
        assert result.skipped
        assert not result.sent

    def test_skipped_is_not_sent(self) -> None:
        """E6, restated: a thing that did not happen must not look like success.

        A caller reading only `sent` shows 'check your inbox' for a message
        nobody wrote.
        """
        assert not SendResult(sent=False, skipped=True).delivered_to_a_server

    def test_a_bare_address_still_produces_a_valid_from_header(self) -> None:
        from neura_core.config import Settings

        mailer = Mailer(Settings(SMTP_FROM="no-reply@example.com"))
        assert mailer._from_header() == "no-reply@example.com"

    def test_a_named_sender_is_preserved(self) -> None:
        from neura_core.config import Settings

        mailer = Mailer(Settings(SMTP_FROM="FiveNeurals <no-reply@example.com>"))
        assert mailer._from_header() == "FiveNeurals <no-reply@example.com>"
