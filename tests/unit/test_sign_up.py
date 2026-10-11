"""ADR-0058 §7, R14 to R17: signing up, without a database.

Held here:

* **the three emails, word for word** (R17, the owner: A): the confirm email
  never repeats what was typed into the form, because anyone can type any text
  there and make us mail it to any address; the approval and refusal emails name
  the shop, which by then a person at FiveNeurals has looked at;
* **the website and the shop's name** are checked and tidied before anything is
  stored, with the words the owner approved;
* **a waiting shop serves nothing**: not servable, no assistant, whatever its
  row says.

Over HTTP and against the database: ``tests/integration/test_console_sign_up.py``.
"""

from __future__ import annotations

import inspect

import pytest

from neura_api.routes.console_sign_up import (
    CONFIRM_SUBJECT,
    approved_email,
    confirm_body,
    refused_email,
)
from neura_core import ValidationError
from neura_core.identity.sign_up import SIGN_UP_TTL, shop_name, shop_website
from neura_core.tenancy import Tenant, TenantStatus

URL = "https://console.example/auth/sign-up?token=abc"


class TestTheEmails:
    def test_the_confirm_email_word_for_word(self) -> None:
        assert CONFIRM_SUBJECT == "Confirm your FiveNeurals sign-up"
        assert confirm_body(URL) == (
            "Hello,\n\n"
            "Someone asked to sign up a shop for FiveNeurals with this email address. "
            "If it was you, use the link below to confirm it.\n\n"
            f"{URL}\n\n"
            "It works once and expires in 15 minutes.\n\n"
            "If it was not you, you can ignore this email. Nothing has been made.\n"
        )

    def test_the_confirm_email_cannot_carry_what_was_typed(self) -> None:
        """The link is all it takes: no shop name, no website, nothing from the form."""
        assert list(inspect.signature(confirm_body).parameters) == ["url"]

    def test_the_link_works_for_15_minutes(self) -> None:
        assert SIGN_UP_TTL.total_seconds() == 15 * 60

    def test_the_approval_email_word_for_word(self) -> None:
        subject, body = approved_email(shop="Tea Leaf", dashboard="https://console.example")
        assert subject == "Tea Leaf is ready on FiveNeurals"
        assert body == (
            "Hello,\n\n"
            "FiveNeurals has approved Tea Leaf. Sign in to start:\n\n"
            "https://console.example\n\n"
            "Your assistant starts in practice mode, so shoppers see none of its replies "
            "until you press Go live. The guide for shop owners shows the next steps:\n\n"
            "https://neura.fiveneurals.com/docs/owners/\n"
        )

    def test_the_refusal_email_word_for_word(self) -> None:
        subject, body = refused_email(shop="Tea Leaf")
        assert subject == "Your FiveNeurals sign-up for Tea Leaf"
        assert body == (
            "Hello,\n\n"
            "Thank you for signing up Tea Leaf for FiveNeurals. We looked at it, and we can't "
            "start an assistant for this shop, so we have removed it. Nothing was charged.\n"
        )

    def test_no_email_has_a_long_dash(self) -> None:
        texts = [
            CONFIRM_SUBJECT,
            confirm_body(URL),
            *approved_email(shop="A Shop", dashboard="https://console.example"),
            *refused_email(shop="A Shop"),
        ]
        assert not [text for text in texts if "—" in text]


class TestTheWebsite:
    @pytest.mark.parametrize(
        ("typed", "kept"),
        [
            ("yourshop.com", "https://yourshop.com"),
            ("  www.tea-leaf.lk/  ", "https://www.tea-leaf.lk"),
            ("https://Shop.Example.com/store", "https://shop.example.com/store"),
            ("http://tea.lk", "http://tea.lk"),
            ("https://shop.example.com:8443/a/b", "https://shop.example.com:8443/a/b"),
            ("https://shop.example.com/?ref=ad#top", "https://shop.example.com"),
        ],
    )
    def test_it_may_be_typed_with_or_without_https(self, typed: str, kept: str) -> None:
        assert shop_website(typed) == kept

    @pytest.mark.parametrize(
        "typed",
        [
            "",
            "   ",
            "not a site",
            "ftp://shop.example.com",
            "javascript:alert(1)",
            "https://localhost",
            "https://user:secret@shop.example.com",
            "https://exa mple.com",
            "https://.com",
            "https://shop..com",
            "https://-shop.com",
            "https://" + "a" * 250 + ".com",
        ],
    )
    def test_anything_else_is_refused_in_plain_words(self, typed: str) -> None:
        with pytest.raises(ValidationError) as refused:
            shop_website(typed)
        assert refused.value.message == "Enter your shop's website, like yourshop.com."


class TestTheShopName:
    def test_spaces_and_line_breaks_are_tidied(self) -> None:
        assert shop_name("  Tea \n  Leaf\t ") == "Tea Leaf"

    @pytest.mark.parametrize("typed", ["", "   ", "x" * 101, "Tea\x00Leaf"])
    def test_an_empty_long_or_unprintable_name_is_refused(self, typed: str) -> None:
        with pytest.raises(ValidationError) as refused:
            shop_name(typed)
        assert refused.value.message == "Enter your shop's name, up to 100 characters."

    def test_100_characters_is_allowed(self) -> None:
        assert shop_name("x" * 100) == "x" * 100


class TestAWaitingShop:
    def test_it_serves_nothing_whatever_its_row_says(self) -> None:
        tenant = Tenant(
            tenant_id="tn_waiting",
            name="Tea Leaf",
            status=TenantStatus("waiting"),
            enabled_agents=frozenset({"care", "sell"}),
        )
        assert tenant.status is TenantStatus.WAITING
        assert not tenant.is_servable
        assert not tenant.may_use("care")
        assert not tenant.may_use("sell")
