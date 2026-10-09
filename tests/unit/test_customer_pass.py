"""The customer pass (ADR-0057 §2, §3): what the shop's server signs for a
signed-in customer, and what NEURA accepts. Pure functions, no database.

Every refusal here is a way someone could otherwise read another person's
orders, so each one is a test of its own."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import jwt
import pytest

from neura_core.tenancy.customer_pass import (
    CUSTOMER_SECRET_PREFIX,
    MAX_PASS_LIFETIME,
    PassStatus,
    check_customer_pass,
    new_customer_secret,
)

SECRET = "fn_cs_" + "k" * 43
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _pass(claims: dict[str, Any] | None = None, *, secret: str = SECRET, **overrides: Any) -> str:
    issued = int(NOW.timestamp())
    body: dict[str, Any] = {"sub": "385", "iat": issued, "exp": issued + 600}
    body.update(claims or {})
    for name, value in overrides.items():
        if value is None:
            body.pop(name, None)
        else:
            body[name] = value
    return jwt.encode(body, secret, algorithm="HS256")


class TestTheSecret:
    def test_it_is_recognisable_and_carries_256_bits(self) -> None:
        secret = new_customer_secret()
        assert secret.startswith(CUSTOMER_SECRET_PREFIX)
        assert CUSTOMER_SECRET_PREFIX == "fn_cs_"
        assert len(secret.removeprefix(CUSTOMER_SECRET_PREFIX)) >= 43
        assert new_customer_secret() != secret


class TestAValidPass:
    def test_names_the_customer(self) -> None:
        result = check_customer_pass(_pass(), SECRET, now=NOW)
        assert result.status is PassStatus.VALID
        assert result.customer_external_id == "385"

    def test_a_clock_a_little_behind_is_forgiven(self) -> None:
        issued = int(NOW.timestamp())
        late = _pass(iat=issued - 600, exp=issued - 30)
        assert check_customer_pass(late, SECRET, now=NOW).status is PassStatus.VALID

    def test_an_id_with_dots_and_slashes_is_kept_as_sent(self) -> None:
        result = check_customer_pass(_pass(sub="gid://shop/Customer/7.1"), SECRET, now=NOW)
        assert result.customer_external_id == "gid://shop/Customer/7.1"


class TestAnExpiredPass:
    def test_is_told_apart_from_a_forged_one(self) -> None:
        """Expired is said only of a pass whose signature is good: the page that
        sent it learns nothing it did not hold (ADR-0057 §5)."""
        issued = int(NOW.timestamp())
        result = check_customer_pass(_pass(iat=issued - 900, exp=issued - 120), SECRET, now=NOW)
        assert result.status is PassStatus.EXPIRED
        assert result.customer_external_id is None

    def test_an_expired_pass_with_a_wrong_signature_is_invalid(self) -> None:
        issued = int(NOW.timestamp())
        forged = _pass(iat=issued - 900, exp=issued - 120, secret="fn_cs_" + "z" * 43)
        assert check_customer_pass(forged, SECRET, now=NOW).status is PassStatus.INVALID


class TestRefused:
    def test_another_shops_secret(self) -> None:
        other = _pass(secret="fn_cs_" + "z" * 43)
        result = check_customer_pass(other, SECRET, now=NOW)
        assert result.status is PassStatus.INVALID
        assert result.customer_external_id is None

    def test_the_none_algorithm(self) -> None:
        unsigned = jwt.encode(
            {"sub": "385", "iat": int(NOW.timestamp()), "exp": int(NOW.timestamp()) + 600},
            None,
            algorithm="none",
        )
        assert check_customer_pass(unsigned, SECRET, now=NOW).status is PassStatus.INVALID

    def test_another_hmac_algorithm(self) -> None:
        issued = int(NOW.timestamp())
        hs512 = jwt.encode(
            {"sub": "385", "iat": issued, "exp": issued + 600}, SECRET, algorithm="HS512"
        )
        assert check_customer_pass(hs512, SECRET, now=NOW).status is PassStatus.INVALID

    @pytest.mark.parametrize("claim", ["sub", "iat", "exp"])
    def test_a_missing_claim(self, claim: str) -> None:
        assert check_customer_pass(_pass(**{claim: None}), SECRET, now=NOW).status is (
            PassStatus.INVALID
        )

    def test_a_pass_that_lasts_longer_than_fifteen_minutes(self) -> None:
        """Otherwise a developer could make a pass that never ends (Q4)."""
        issued = int(NOW.timestamp())
        too_long = _pass(exp=issued + int(MAX_PASS_LIFETIME.total_seconds()) + 1)
        assert check_customer_pass(too_long, SECRET, now=NOW).status is PassStatus.INVALID
        exactly = _pass(exp=issued + int(MAX_PASS_LIFETIME.total_seconds()))
        assert check_customer_pass(exactly, SECRET, now=NOW).status is PassStatus.VALID

    @pytest.mark.parametrize(
        "extra",
        [{"email": "jane@example.com"}, {"name": "Jane"}, {"aud": "neura"}, {"jti": "1"}],
    )
    def test_any_other_claim(self, extra: dict[str, str]) -> None:
        """Only the customer's id, so nothing more about a shopper is sent by
        mistake (ADR-0057 §2)."""
        result = check_customer_pass(_pass(extra), SECRET, now=NOW)
        assert result.status is PassStatus.INVALID
        assert "claim" in result.reason

    @pytest.mark.parametrize("sub", ["", " ", "a" * 129, "38\n5", "38\t5", 385])
    def test_an_unusable_customer_id(self, sub: Any) -> None:
        assert check_customer_pass(_pass(sub=sub), SECRET, now=NOW).status is PassStatus.INVALID

    @pytest.mark.parametrize("sub", [385, 3.5, True, ["385"], {"id": "385"}])
    def test_a_customer_id_that_is_not_text_says_so(self, sub: Any) -> None:
        """Most shops keep a customer's id as a number, so `'sub' => $id` is the
        first pass many developers write. The reason must say what to change,
        not *not a customer pass* (G83)."""
        result = check_customer_pass(_pass(sub=sub), SECRET, now=NOW)
        assert result.status is PassStatus.INVALID
        assert "sub must be text" in result.reason
        assert '"385", not 385' in result.reason

    def test_an_extra_claim_of_any_type_is_named(self) -> None:
        """The library checks `jti` too, before our rule would name it."""
        result = check_customer_pass(_pass({"jti": 7}), SECRET, now=NOW)
        assert result.status is PassStatus.INVALID
        assert "jti" in result.reason

    def test_a_pass_made_in_the_future(self) -> None:
        issued = int(NOW.timestamp()) + 600
        early = _pass(iat=issued, exp=issued + 300)
        assert check_customer_pass(early, SECRET, now=NOW).status is PassStatus.INVALID

    @pytest.mark.parametrize("text", ["", "not a pass", "a.b.c", "x" * 5000])
    def test_anything_that_is_not_a_pass(self, text: str) -> None:
        assert check_customer_pass(text, SECRET, now=NOW).status is PassStatus.INVALID

    def test_the_secret_itself_sent_as_a_pass(self) -> None:
        """A developer who puts the secret in the page instead of a pass made
        with it. Refused, and told plainly, because the secret is now public."""
        result = check_customer_pass(SECRET, SECRET, now=NOW)
        assert result.status is PassStatus.INVALID
        assert "secret" in result.reason
        assert "new" in result.reason
        assert SECRET not in result.reason

    def test_no_secret_made_yet(self) -> None:
        """A shop whose owner never made the secret has no signed-in shoppers."""
        assert check_customer_pass(_pass(), None, now=NOW).status is PassStatus.INVALID

    def test_a_reason_never_repeats_the_pass(self) -> None:
        token = _pass({"email": "jane@example.com"})
        reason = check_customer_pass(token, SECRET, now=NOW).reason
        assert token not in reason
        assert "jane@example.com" not in reason
