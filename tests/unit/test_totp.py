"""The admin's code from their phone (ADR-0067 §5): TOTP, RFC 6238, without a library.

A hand-written authenticator is only as good as its agreement with every phone
app, so the first test is **the RFC's own table** (Appendix B, SHA-1), cut to 6
digits as every authenticator app shows them.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

from neura_core.identity.totp import STEP_SECONDS, code_at, matching_step, new_secret, otpauth_uri

#: RFC 6238 Appendix B's SHA-1 seed, as an authenticator app would hold it.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.mark.parametrize(
    ("unix_time", "code"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
    ],
)
def test_the_rfcs_own_values(unix_time: int, code: str) -> None:
    assert code_at(RFC_SECRET, unix_time // STEP_SECONDS) == code


def _at(unix_time: int) -> datetime:
    return datetime.fromtimestamp(unix_time, tz=UTC)


class TestMatching:
    def test_the_current_code_matches_its_step(self) -> None:
        step = 1234567890 // STEP_SECONDS
        assert matching_step(RFC_SECRET, "005924", now=_at(1234567890), last_step=None) == step

    def test_the_code_before_and_after_are_accepted(self) -> None:
        """A phone's clock drifts: 30 seconds either side still works."""
        now = 1234567890
        step = now // STEP_SECONDS
        for other in (step - 1, step + 1):
            code = code_at(RFC_SECRET, other)
            assert matching_step(RFC_SECRET, code, now=_at(now), last_step=None) == other

    def test_an_older_code_is_refused(self) -> None:
        now = 1234567890
        old = code_at(RFC_SECRET, now // STEP_SECONDS - 2)
        assert matching_step(RFC_SECRET, old, now=_at(now), last_step=None) is None

    def test_a_code_works_once(self) -> None:
        now = 1234567890
        step = now // STEP_SECONDS
        assert matching_step(RFC_SECRET, "005924", now=_at(now), last_step=step) is None

    @pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", " 005924x"])
    def test_a_code_that_is_not_six_digits_is_refused(self, code: str) -> None:
        assert matching_step(RFC_SECRET, code, now=_at(1234567890), last_step=None) is None

    def test_spaces_a_person_types_are_ignored(self) -> None:
        assert matching_step(RFC_SECRET, "005 924", now=_at(1234567890), last_step=None)


def test_a_new_secret_is_random_and_an_app_can_read_it() -> None:
    first, second = new_secret(), new_secret()
    assert first != second
    assert len(base64.b32decode(first + "=" * (-len(first) % 8))) == 20


def test_the_address_an_app_scans() -> None:
    uri = otpauth_uri("JBSWY3DPEHPK3PXP", account="admin@fiveneurals.test")
    assert uri.startswith("otpauth://totp/FiveNeurals:admin%40fiveneurals.test?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=FiveNeurals" in uri
