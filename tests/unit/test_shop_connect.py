"""ADR-0052 without a database: the address rule, the token, and the one cause.

The address rule (§3, G47) is the part an attacker would aim at, so every range
it must refuse is named here rather than trusted to ``is_global``. The diagnosis
(§4, G48) is the part an owner reads first, so each cause is produced from a real
bridge (the reference store) rather than asserted about a dictionary.
"""

from __future__ import annotations

import httpx
import pytest

from neura_adapters.generic.adapter import GenericAdapter
from neura_adapters.generic.reference import DEFAULT_TOKEN, Defect, ReferenceStore
from neura_api.addresses import (
    ADDRESS_INVALID,
    ADDRESS_NOT_HTTPS,
    ADDRESS_NOT_PUBLIC,
    check_shop_address,
)
from neura_api.jobs.shop_check import (
    NO_BRIDGE,
    TOKEN_REFUSED,
    developer_text,
    diagnose,
    outcome,
)
from neura_commerce import check_adapter
from neura_core import ValidationError
from neura_core.tenancy import SHOP_TOKEN_PREFIX, new_shop_token
from neura_domain import Capability


def adapter_for(store: ReferenceStore, *, token: str | None, base_url: str | None = None):
    return GenericAdapter(
        base_url=base_url or store.base_url(),
        tenant_id="tn_unit",
        token=token,
        transport=store.transport(),
    )


class TestTheAddressRule:
    @pytest.mark.parametrize(
        "address",
        [
            "https://127.0.0.1/neura/v1",
            "https://10.0.0.5/neura/v1",
            "https://192.168.1.10/neura/v1",
            "https://172.16.0.1/neura/v1",
            "https://169.254.169.254/latest/meta-data",
            "https://100.64.0.1/neura/v1",
            "https://0.0.0.0/neura/v1",
            "https://[::1]/neura/v1",
            "https://[::ffff:127.0.0.1]/neura/v1",
            "https://[fd00::1]/neura/v1",
            "https://224.0.0.1/neura/v1",
        ],
    )
    async def test_production_never_calls_a_private_address(self, address: str) -> None:
        with pytest.raises(ValidationError) as refused:
            await check_shop_address(address, production=True)
        assert refused.value.code == ADDRESS_NOT_PUBLIC
        assert refused.value.message == (
            "This address isn't on the public internet, so NEURA won't call it."
        )

    async def test_production_wants_https(self) -> None:
        with pytest.raises(ValidationError) as refused:
            await check_shop_address("http://93.184.216.34/neura/v1", production=True)
        assert refused.value.code == ADDRESS_NOT_HTTPS

    async def test_a_public_address_is_allowed_and_tidied(self) -> None:
        assert (
            await check_shop_address(" https://93.184.216.34/neura/v1/ ", production=True)
            == "https://93.184.216.34/neura/v1"
        )

    @pytest.mark.parametrize(
        "address",
        ["", "yourshop.example/neura/v1", "ftp://shop.example/neura/v1", "https:///neura/v1"],
    )
    async def test_something_that_is_not_a_web_address_is_refused(self, address: str) -> None:
        with pytest.raises(ValidationError) as refused:
            await check_shop_address(address, production=False)
        assert refused.value.code == ADDRESS_INVALID

    async def test_a_password_in_the_address_is_refused(self) -> None:
        with pytest.raises(ValidationError) as refused:
            await check_shop_address("https://user:secret@shop.example/neura/v1", production=False)
        assert refused.value.code == ADDRESS_INVALID

    async def test_outside_production_a_test_shop_on_this_machine_is_allowed(self) -> None:
        """Our test shops run on the developer's own machine (ADR-0052 §3)."""
        assert (
            await check_shop_address("http://ecommerce.test/neura/v1", production=False)
            == "http://ecommerce.test/neura/v1"
        )
        assert await check_shop_address("http://127.0.0.1:8787/neura/v1", production=False)


class TestTheToken:
    def test_it_is_long_random_and_recognisable(self) -> None:
        tokens = {new_shop_token() for _ in range(200)}
        assert len(tokens) == 200
        assert all(t.startswith(SHOP_TOKEN_PREFIX) for t in tokens)
        # 32 random bytes, base64url: 43 characters after the prefix.
        assert all(len(t) == len(SHOP_TOKEN_PREFIX) + 43 for t in tokens)


class TestOneCauseFirst:
    """G48: one wrong token used to read as eight unrelated failures."""

    async def test_a_wrong_token_is_one_cause(self) -> None:
        store = ReferenceStore()
        adapter = adapter_for(store, token="not-the-right-token")
        cause, capabilities = await diagnose(adapter)
        await adapter.aclose()
        assert cause == TOKEN_REFUSED
        assert "product.read" in capabilities

    async def test_the_right_token_has_no_cause(self) -> None:
        store = ReferenceStore()
        adapter = adapter_for(store, token=DEFAULT_TOKEN)
        cause, _ = await diagnose(adapter)
        await adapter.aclose()
        assert cause is None

    async def test_an_address_with_no_bridge_says_so(self) -> None:
        store = ReferenceStore()
        adapter = adapter_for(store, token=DEFAULT_TOKEN, base_url="https://store.example.com/x")
        cause, _ = await diagnose(adapter)
        await adapter.aclose()
        assert cause == NO_BRIDGE

    async def test_the_developer_text_names_the_cause_first_and_no_private_file(self) -> None:
        store = ReferenceStore()
        adapter = adapter_for(store, token="not-the-right-token")
        report = await check_adapter(adapter)
        await adapter.aclose()

        result = outcome("https://shop.example/neura/v1", cause=TOKEN_REFUSED, report=report)
        lines = result["text"].splitlines()
        assert lines[2].startswith("The bridge refused the shop token")
        assert "docs/spec" not in result["text"]  # G17
        assert result["conformant"] is False

    async def test_a_clean_run_is_conformant_and_carries_no_token(self) -> None:
        store = ReferenceStore()
        adapter = adapter_for(store, token=DEFAULT_TOKEN)
        report = await check_adapter(adapter)
        await adapter.aclose()

        result = outcome("https://shop.example/neura/v1", cause=None, report=report)
        assert result["conformant"] is True
        assert result["failed"] == 0
        assert DEFAULT_TOKEN not in str(result)


class TestOneCheckForTerminalAndDashboard:
    async def test_check_adapter_runs_the_wire_checks_too(self) -> None:
        """The dashboard's check is the terminal tool's, not a smaller copy."""
        store = ReferenceStore()
        adapter = adapter_for(store, token=DEFAULT_TOKEN)
        report = await check_adapter(adapter)
        await adapter.aclose()
        ran = set(report.passed_checks) | {f.check for f in report.findings}
        assert {"auth.required", "auth.rejects_wrong_token", "health.spec_version"} <= ran
        assert {"products.get_missing", "pagination"} <= ran

    async def test_a_shop_with_only_its_products_can_connect(self) -> None:
        """G50: the guide's first three addresses are enough to connect, even when
        the bridge answers 404 for an address it never built before checking the
        token. The owner's Connect used to stay locked by two false failures."""
        store = ReferenceStore(
            capabilities=frozenset({Capability.PRODUCT_READ, Capability.PRODUCT_SEARCH})
        )

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path.removeprefix(store.prefix)
            if path in ("/health", "/products") or path.startswith("/products/"):
                return store.handle(request)
            return httpx.Response(404, json={"error": f"no such endpoint: {path}"})

        adapter = GenericAdapter(
            base_url=store.base_url(),
            tenant_id="tn_unit",
            token=DEFAULT_TOKEN,
            transport=httpx.MockTransport(handle),
        )
        cause, _ = await diagnose(adapter)
        report = await check_adapter(adapter)
        await adapter.aclose()

        result = outcome("https://shop.example/neura/v1", cause=cause, report=report)
        assert result["conformant"] is True, result["text"]

    async def test_products_without_a_status_warn_and_still_connect(self) -> None:
        """G69: a warning, not a failure, and it travels with the result the owner's
        screen reads (G75), not only in the developer's copy."""
        store = ReferenceStore(defects=frozenset({Defect.NO_PRODUCT_STATUS}))
        adapter = adapter_for(store, token=DEFAULT_TOKEN)
        report = await check_adapter(adapter)
        await adapter.aclose()

        result = outcome("https://shop.example/neura/v1", cause=None, report=report)
        assert result["conformant"] is True, result["text"]
        assert result["warnings"] == 1
        assert [f["check"] for f in result["findings"]] == ["products.status_vocabulary"]
        assert "⚠ products.status_vocabulary" in result["text"]

    def test_developer_text_without_a_report_still_says_why(self) -> None:
        assert "Could not reach" in developer_text("https://x.example", "unreachable", None, None)
