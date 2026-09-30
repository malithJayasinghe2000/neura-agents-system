"""neura-core behaviour that other layers depend on."""

from __future__ import annotations

import logging

import pytest

from neura_core import ConfigurationError, bind_context, current_context, new_id
from neura_core.config import Environment, Settings
from neura_core.crypto import decrypt, encrypt, generate_key, unwrap_dek, wrap_dek
from neura_core.ids import CONVERSATION, is_valid
from neura_core.logging import _redact, _StdlibRedactionFilter


class TestIds:
    def test_prefixed_and_valid(self) -> None:
        cid = new_id(CONVERSATION)
        assert cid.startswith("cnv_")
        assert is_valid(cid, CONVERSATION)

    def test_wrong_prefix_is_invalid(self) -> None:
        assert not is_valid(new_id(CONVERSATION), "tn")

    def test_ids_are_time_sortable(self) -> None:
        ids = [new_id(CONVERSATION) for _ in range(20)]
        assert ids == sorted(ids)


class TestRedaction:
    def test_sensitive_keys_are_replaced(self) -> None:
        assert _redact("hunter2", "password") == "[REDACTED]"
        assert _redact("fn_sk_abc", "api_key") == "[REDACTED]"

    def test_nested_structures_are_scrubbed(self) -> None:
        result = _redact({"outer": {"token": "abc123", "safe": "visible"}})
        assert result["outer"]["token"] == "[REDACTED]"
        assert result["outer"]["safe"] == "visible"

    def test_secrets_in_free_text_are_scrubbed(self) -> None:
        """A key leaking through an exception message is the realistic case."""
        scrubbed = _redact("failed for jane@example.com using fn_sk_abcdefgh123", "detail")
        assert "jane@example.com" not in scrubbed
        assert "fn_sk_abcdefgh123" not in scrubbed


class TestStdlibRedaction:
    """G34 in CONNECTING_A_NEW_SHOP_LOG.md: the web server's request line printed
    the chat socket's whole address, key included. It logs through the standard
    library, which the structlog processor never sees."""

    def _render(self, template: str, *args: object) -> str:
        record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, template, args, None)
        assert _StdlibRedactionFilter().filter(record) is True, "scrubs, never drops"
        return record.getMessage()

    def test_a_key_in_a_socket_address_is_hidden(self) -> None:
        line = self._render(
            '%s - "WebSocket %s" [accepted]',
            "127.0.0.1:52235",
            "/v1/stream?token=fn_pk_test_E2K4MOaMCJru2KwvFevuZSez7vv9MU6QPrdVMgC11h8",
        )
        assert "E2K4MOaM" not in line
        assert line == '127.0.0.1:52235 - "WebSocket /v1/stream?token=***" [accepted]'

    def test_any_token_in_an_address_is_hidden_and_the_rest_kept(self) -> None:
        line = self._render('"GET %s HTTP/1.1" %d', "/auth/verify?token=abc.def&next=/x", 200)
        assert line == '"GET /auth/verify?token=***&next=/x HTTP/1.1" 200'


class TestCrypto:
    def test_round_trip(self) -> None:
        key = generate_key()
        assert decrypt(encrypt("s3cret", key), key) == "s3cret"

    def test_ciphertext_differs_each_time(self) -> None:
        """A fresh nonce per encryption — identical plaintexts must not be linkable."""
        key = generate_key()
        assert encrypt("same", key) != encrypt("same", key)

    def test_dek_is_bound_to_its_tenant(self) -> None:
        """A wrapped key moved to another tenant's row must fail to unwrap,
        rather than silently working."""
        kek, dek = generate_key(), generate_key()
        wrapped = wrap_dek(dek, kek, tenant_id="tn_a")
        assert unwrap_dek(wrapped, kek, tenant_id="tn_a") == dek
        with pytest.raises(Exception):  # noqa: B017 - cryptography raises InvalidTag
            unwrap_dek(wrapped, kek, tenant_id="tn_b")

    def test_malformed_key_is_a_configuration_error(self) -> None:
        with pytest.raises(ConfigurationError):
            encrypt("x", "not-base64!!")


class TestContext:
    def test_binds_and_restores(self) -> None:
        assert current_context() == {}
        with bind_context(tenant_id="tn_1", trace_id="req_1"):
            ctx = current_context()
            assert ctx["tenant_id"] == "tn_1"
            assert ctx["trace_id"] == "req_1"
        # Restoration matters: a leaked tenant_id would misattribute activity.
        assert current_context() == {}

    def test_nested_binding_restores_outer_value(self) -> None:
        with bind_context(tenant_id="tn_a"):
            with bind_context(tenant_id="tn_b"):
                assert current_context()["tenant_id"] == "tn_b"
            assert current_context()["tenant_id"] == "tn_a"


class TestSettings:
    def test_development_tolerates_placeholder_secrets(self) -> None:
        """A fresh clone must boot without ceremony."""
        Settings(NEURA_ENV="development").validate_for_runtime()

    def test_production_rejects_placeholder_secrets(self) -> None:
        settings = Settings(
            NEURA_ENV="production", NEURA_SECRET_KEY="change-me", NEURA_KEK="change-me"
        )
        with pytest.raises(ConfigurationError) as exc:
            settings.validate_for_runtime()
        assert "NEURA_SECRET_KEY" in str(exc.value)

    def test_widget_origins_are_parsed(self) -> None:
        settings = Settings(WIDGET_ALLOWED_ORIGINS="https://a.com, https://b.com")
        assert settings.widget_origins == ["https://a.com", "https://b.com"]

    def test_hard_budget_below_soft_is_rejected(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            Settings(BUDGET_DAILY_COST_USD_SOFT=10.0, BUDGET_DAILY_COST_USD_HARD=5.0)

    def test_is_production(self) -> None:
        assert Settings(NEURA_ENV="production").env is Environment.PRODUCTION
        assert Settings(NEURA_ENV="production").is_production
