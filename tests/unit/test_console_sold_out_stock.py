"""The Sold out screen's "now" — the rule that turns one stock lookup into a
label per product (console.md §3.7).

The rule is the shop's own for a view (ADR-0049): a product can be bought when
**any** of its variants has stock. And one thing it must never do: call a
product the shop said nothing about "sold out".
"""

from __future__ import annotations

from neura_api.routes.console_sold_out import in_stock_by_product
from neura_domain import InventoryLevel


def _level(variant: str, quantity: int) -> InventoryLevel:
    return InventoryLevel(variant_external_id=variant, quantity=quantity, in_stock=quantity > 0)


def test_one_variant_in_stock_is_enough() -> None:
    result = in_stock_by_product({"p1": ["s", "m"]}, [_level("s", 0), _level("m", 3)])
    assert result == {"p1": True}


def test_every_variant_out_is_still_sold_out() -> None:
    result = in_stock_by_product({"p1": ["s", "m"]}, [_level("s", 0), _level("m", 0)])
    assert result == {"p1": False}


def test_a_product_the_shop_said_nothing_about_is_left_out() -> None:
    """Deleted from the shop, or never synced: unknown, not sold out."""
    result = in_stock_by_product({"p1": ["p1"], "gone": ["gone"]}, [_level("p1", 0)])
    assert result == {"p1": False}


def test_variants_are_never_mixed_between_products() -> None:
    result = in_stock_by_product(
        {"jumper": ["j-s"], "shell": ["sh-m"]}, [_level("j-s", 2), _level("sh-m", 0)]
    )
    assert result == {"jumper": True, "shell": False}
