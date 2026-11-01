"""Links that count their clicks: what needs no database (ADR-0074).

* **the code** (§2): 6 characters, no look-alikes, and nothing else accepted;
* **the labels** (§4): the date and year and the post for a plan's link, the
  name for an own link, and the medium from the place;
* **the places** (R111, R112): a social post has Facebook, Instagram and
  WhatsApp; the email one; the banner none;
* **robots** (§5): preview fetchers, search engines and scripts are not
  counted; a person's browser is, whatever phone it is on.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs

import pytest

from neura_agent_core.links import (
    CODE_ALPHABET,
    CODE_LENGTH,
    POST_PLACES,
    Place,
    Post,
    campaign_labels,
    is_code,
    is_robot,
    new_code,
    own_labels,
    short_link,
    slug,
)


class TestTheCode:
    def test_a_code_is_six_characters_without_look_alikes(self) -> None:
        for _ in range(200):
            code = new_code()
            assert len(code) == CODE_LENGTH
            assert set(code) <= set(CODE_ALPHABET)
            assert not set(code) & set("0o1l")
            assert is_code(code)

    @pytest.mark.parametrize(
        "value", ["", "k7m2q", "k7m2qa1", "K7M2QA", "k7m2q0", "../etc", "k7m2q?", "k7 2qa"]
    )
    def test_anything_else_is_not_a_code(self, value: str) -> None:
        assert not is_code(value)

    def test_the_short_link_is_the_base_and_the_code(self) -> None:
        assert (
            short_link("https://go.fiveneurals.com/", "k7m2qa")
            == "https://go.fiveneurals.com/k7m2qa"
        )
        assert short_link("http://localhost:8010/go", "k7m2qa") == "http://localhost:8010/go/k7m2qa"


class TestTheLabels:
    def test_a_plan_link_says_the_date_and_year_and_the_post(self) -> None:
        labels = parse_qs(
            campaign_labels(
                campaign="Avurudu",
                day=date(2027, 4, 14),
                post=Post.LAST_CHANCE,
                place=Place.WHATSAPP,
            )
        )
        assert labels == {
            "utm_source": ["whatsapp"],
            "utm_medium": ["social"],
            "utm_campaign": ["avurudu-2027"],
            "utm_content": ["last-chance"],
        }

    def test_the_email_is_its_own_medium(self) -> None:
        labels = parse_qs(
            campaign_labels(
                campaign="Black Friday", day=date(2027, 11, 26), post=Post.EMAIL, place=Place.EMAIL
            )
        )
        assert labels["utm_medium"] == ["email"]
        assert labels["utm_campaign"] == ["black-friday-2027"]
        assert labels["utm_content"] == ["email"]

    def test_an_own_link_is_named_by_its_name_and_has_no_content(self) -> None:
        labels = parse_qs(own_labels(name="Tuesday post", place=Place.FACEBOOK))
        assert labels == {
            "utm_source": ["facebook"],
            "utm_medium": ["social"],
            "utm_campaign": ["tuesday-post"],
        }
        assert parse_qs(own_labels(name="x", place=Place.OTHER))["utm_medium"] == ["other"]

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Avurudu", "avurudu"),
            ("Ceylon Harvester's 5th birthday", "ceylon-harvester-s-5th-birthday"),
            ("  11.11  ", "11-11"),
            ("Sinhala & Tamil New Year!", "sinhala-tamil-new-year"),
            ("අවුරුදු", "link"),
            ("", "link"),
        ],
    )
    def test_a_name_becomes_a_label(self, name: str, expected: str) -> None:
        assert slug(name) == expected


class TestThePlaces:
    def test_a_social_post_has_a_link_for_each_place_and_the_email_one(self) -> None:
        social = (Place.FACEBOOK, Place.INSTAGRAM, Place.WHATSAPP)
        assert POST_PLACES[Post.TEASER] == social
        assert POST_PLACES[Post.LAUNCH] == social
        assert POST_PLACES[Post.LAST_CHANCE] == social
        assert POST_PLACES[Post.EMAIL] == (Place.EMAIL,)

    def test_the_banner_has_no_link(self) -> None:
        assert "banner" not in {post.value for post in POST_PLACES}


class TestRobots:
    @pytest.mark.parametrize(
        "agent",
        [
            "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "WhatsApp/2.23.20.0 A",
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "Twitterbot/1.0",
            "TelegramBot (like TwitterBot)",
            "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
            "meta-externalagent/1.1",
            "curl/8.4.0",
            "python-httpx/0.27.0",
            "",
            None,
        ],
    )
    def test_previews_search_engines_and_scripts_are_not_counted(self, agent: str | None) -> None:
        assert is_robot(agent)

    @pytest.mark.parametrize(
        "agent",
        [
            # Safari on an iPhone, Chrome on Android, Facebook's and Instagram's
            # own browsers, and a phone whose name ends in "bot".
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBAV/450.0.0.38.108;FBBV/123]",
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Mobile Safari/537.36 Instagram 312.0.0.32.112 Android",
            "Mozilla/5.0 (Linux; Android 10; CUBOT X30) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Mobile Safari/537.36",
        ],
    )
    def test_a_persons_browser_is_counted(self, agent: str) -> None:
        assert not is_robot(agent)


class TestTheAccessLog:
    """uvicorn's access line prints the phone's address first: dropped for a tap."""

    def _record(self, path: str):
        import logging

        return logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("203.0.113.9:51234", "GET", path, "1.1", 302),
            None,
        )

    def test_a_tap_has_no_access_line(self) -> None:
        from neura_api.routes.go import TapAddressFilter

        assert not TapAddressFilter().filter(self._record("/go/k7m2qa"))

    def test_every_other_path_keeps_its_line(self) -> None:
        from neura_api.routes.go import TapAddressFilter

        assert TapAddressFilter().filter(self._record("/v1/health/ready"))
        assert TapAddressFilter().filter(self._record("/v1/console/shops/tn_1/links"))
