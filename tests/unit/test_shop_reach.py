"""Where NEURA's server connects: only public addresses, checked when it connects.

G47's open half (DNS rebinding, ADR-0052 §3) and G78. The address a shop gave
us was checked when the owner pressed Check or Connect, then looked up again to
connect, and never checked again on any later call. A name can answer a public
address to the check and one of ours a moment later, or the next day. In
production every call to a shop and every webhook now goes through one
connection that looks the name up once, refuses it unless every answer is
public, and connects to exactly the address it checked.

No internet: names are answered from a table (``tests.reach``) and "our own
private network" is a listener on 127.0.0.1 that counts connections.
"""

from __future__ import annotations

import httpx
import pytest

from neura_api.jobs.shop_check import UNREACHABLE, ShopCheckHandler
from neura_core import ValidationError, get_settings
from neura_core.webhooks import Delivery, WebhookEvent
from tests.reach import PUBLIC, answer_names, private_listener

TOKEN = {"token": "the-shop-token"}


async def test_the_check_never_connects_to_a_name_that_changes_its_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rebinding itself: public when checked, ours when connected to."""
    async with private_listener() as inside:
        answer_names(monkeypatch, {"shop.rebind.example": [[PUBLIC], ["127.0.0.1"]]})

        result = await ShopCheckHandler(production=True)._run(
            f"https://shop.rebind.example:{inside.port}/neura/v1", "generic", "tn_unit", TOKEN
        )

        assert inside.hits == [], "NEURA's server connected to a private address"
        assert result["cause"] == UNREACHABLE


@pytest.mark.parametrize(
    "answers",
    [
        ["127.0.0.1"],
        ["10.0.0.5"],
        ["169.254.169.254"],
        ["::1"],
        ["::ffff:127.0.0.1"],
        [PUBLIC, "127.0.0.1"],
    ],
)
async def test_a_private_answer_is_refused_by_the_connection_itself(
    monkeypatch: pytest.MonkeyPatch, answers: list[str]
) -> None:
    """Every answer must be public: one private one among public ones is refused too."""
    from neura_api.addresses import outbound_transport

    async with private_listener() as inside:
        answer_names(monkeypatch, {"internal.example": [answers]})
        transport = outbound_transport(production=True)
        assert transport is not None
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.ConnectError, match="not on the public internet"):
                await client.get(f"https://internal.example:{inside.port}/neura/v1/health")

        assert inside.hits == []


async def test_a_public_answer_is_connected_to_that_exact_address_by_its_own_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One lookup per connection, the checked address dialled, and the request still
    names the shop (TLS checks the certificate against that name, not the address)."""
    import neura_api.addresses as addresses
    from neura_api.addresses import outbound_transport

    # The listener stands in for a public shop: only its address is on our machine.
    monkeypatch.setattr(addresses, "_is_public", lambda ip: True)
    async with private_listener(answer_http=True) as shop:
        asked = answer_names(monkeypatch, {"shop.example": [["127.0.0.1"]]})
        transport = outbound_transport(production=True)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get(f"http://shop.example:{shop.port}/neura/v1/health")

    assert response.status_code == 200
    assert shop.hosts == [f"shop.example:{shop.port}"]
    assert asked["shop.example"] == 1


async def test_outside_production_shops_are_called_as_before() -> None:
    """The test shops run on the developer's own machine (ADR-0052 §3)."""
    from neura_api.addresses import outbound_transport

    assert outbound_transport(production=False) is None


async def test_a_webhook_is_never_posted_to_a_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G78 (b): the address a shop registers for webhooks gets the same rule."""
    from neura_api.webhooks import WebhookDrainer, deliver

    monkeypatch.setenv("NEURA_ENV", "production")
    get_settings.cache_clear()
    try:
        drainer = WebhookDrainer(db=None)  # type: ignore[arg-type]
        async with private_listener() as inside:
            answer_names(monkeypatch, {"hooks.rebind.example": [["127.0.0.1"]]})
            attempt = await deliver(
                drainer._client,
                url=f"https://hooks.rebind.example:{inside.port}/in",
                secret="whsec",
                delivery=Delivery(
                    id="dlv_1",
                    tenant_id="tn_unit",
                    endpoint_id="whe_1",
                    event=WebhookEvent.CONVERSATION_ESCALATED,
                    event_id="evt_1",
                ),
            )
        await drainer.aclose()
    finally:
        get_settings.cache_clear()

    assert inside.hits == []
    assert not attempt.ok


@pytest.mark.parametrize(
    "url", ["https://10.0.0.5/hooks", "https://169.254.169.254/latest", "https://[::1]/hooks"]
)
async def test_registering_a_private_webhook_address_is_refused_in_production(url: str) -> None:
    from neura_api.addresses import ADDRESS_NOT_PUBLIC, check_webhook_address

    with pytest.raises(ValidationError) as refused:
        await check_webhook_address(url, production=True)
    assert refused.value.code == ADDRESS_NOT_PUBLIC


async def test_a_public_webhook_address_and_any_address_outside_production_are_kept() -> None:
    from neura_api.addresses import check_webhook_address

    await check_webhook_address(f"https://{PUBLIC}/hooks", production=True)
    await check_webhook_address("http://localhost:4000/hooks", production=False)
