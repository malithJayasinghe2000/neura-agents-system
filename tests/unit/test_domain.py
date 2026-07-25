"""The canonical model's invariants.

Each test corresponds to a rule in docs/architecture/commerce-integration.md §2.2
that exists because of a specific class of bug.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from neura_domain import Money, Order, OrderStatus, Product, ProductVariant


def _now() -> datetime:
    return datetime.now(UTC)


class TestMoney:
    def test_accepts_decimal_and_string(self) -> None:
        assert Money(amount=Decimal("19.99"), currency="USD").amount == Decimal("19.99")
        assert Money(amount="19.99", currency="USD").amount == Decimal("19.99")  # type: ignore[arg-type]

    def test_rejects_float(self) -> None:
        """Floats in commerce produce wrong totals that cannot be fixed afterwards.

        By the time a float arrives the precision is already gone, so it is
        rejected at the boundary rather than silently converted.
        """
        with pytest.raises(ValidationError):
            Money(amount=19.99, currency="USD")  # type: ignore[arg-type]

    def test_currency_must_be_iso_4217(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=Decimal("1"), currency="dollars")


class TestCanonicalEntity:
    def test_external_id_is_coerced_to_string(self) -> None:
        """Platforms use ints, UUIDs and slugs; we normalise to str at the boundary."""
        product = Product(
            neura_id="ne_1",
            tenant_id="tn_1",
            external_id=1001,  # type: ignore[arg-type]
            platform="generic",
            synced_at=_now(),
            title="Kettle",
        )
        assert product.external_id == "1001"

    def test_naive_timestamps_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Product(
                neura_id="ne_1",
                tenant_id="tn_1",
                external_id="1",
                platform="generic",
                synced_at=datetime(2026, 7, 25),  # noqa: DTZ001
                title="Kettle",
            )

    def test_raw_payload_is_preserved(self) -> None:
        """No canonical model survives every platform; keeping the source payload
        turns an unmapped field into a lookup rather than a re-sync."""
        product = Product(
            neura_id="ne_1",
            tenant_id="tn_1",
            external_id="1",
            platform="generic",
            synced_at=_now(),
            title="Kettle",
            raw={"vendor_specific_field": "value"},
        )
        assert product.raw is not None
        assert product.raw["vendor_specific_field"] == "value"


class TestOrder:
    def test_status_defaults_to_unknown(self) -> None:
        """An unmappable platform status becomes UNKNOWN — it never leaks a
        platform-specific string into the agent's reasoning."""
        order = Order(
            neura_id="ne_1",
            tenant_id="tn_1",
            external_id="1001",
            platform="generic",
            synced_at=_now(),
            order_number="1001",
        )
        assert order.status is OrderStatus.UNKNOWN

    def test_tracking_numbers_collects_across_fulfillments(self) -> None:
        from neura_domain import Fulfillment

        order = Order(
            neura_id="ne_1",
            tenant_id="tn_1",
            external_id="1001",
            platform="generic",
            synced_at=_now(),
            order_number="1001",
            fulfillments=[
                Fulfillment(tracking_number="TRK1"),
                Fulfillment(tracking_number=None),
                Fulfillment(tracking_number="TRK2"),
            ],
        )
        assert order.tracking_numbers == ["TRK1", "TRK2"]


class TestProductSearchableText:
    def test_includes_title_description_and_variant_options(self) -> None:
        product = Product(
            neura_id="ne_1",
            tenant_id="tn_1",
            external_id="1",
            platform="generic",
            synced_at=_now(),
            title="Cast Iron Skillet",
            description="Pre-seasoned, oven safe.",
            variants=[ProductVariant(external_id="v1", title="30cm", options={"size": "30cm"})],
        )
        text = product.searchable_text()
        assert "Cast Iron Skillet" in text
        assert "Pre-seasoned" in text
        assert "size: 30cm" in text
