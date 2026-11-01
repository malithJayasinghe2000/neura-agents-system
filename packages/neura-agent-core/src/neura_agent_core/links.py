"""Links that count their clicks: ADR-0074's data.

A link is ``<LINKS_BASE_URL>/<code>``. A tap on it adds 1 to that link's count
for the day and sends the shopper on to the product's own page, with the
campaign labels added (R109). Two kinds, one table:

* **a plan's link** (R110, R111): one post of one Marketing calendar plan
  (teaser, launch, last chance, the email), one place (Facebook, Instagram,
  WhatsApp, or the email), one product. Made the first time the owner copies
  it; copying the same post, place and product again gives the same link;
* **an own link** (D18, R114): any product, any place, named by the owner on
  the Links page.

**Here, in the shared core, beside** :mod:`neura_agent_core.calendar`, for the
reason the other GROW pages' data is: the pages are the console's own, and the
console may not learn an agent's name (AGENTS.md, G88).

**What is kept** (ADR-0074 §5, R116, R118): a link, and **one number per link
per day**. Never anything about the person who tapped: no address, no browser
name, no cookie, no visit. A link stays until the owner removes it; *Remove*
deletes its clicks and keeps what forwarding needs, so a link in an old post
keeps opening its product (R113). A plan's deletion does not touch its links.
Shop removal knows both tables (G76).

**The redirect is the one place a request arrives before the shop is known**
(§7): it has only the code. It runs ``neura_follow_link()`` in
:meth:`Database.follow_session`, a ``SECURITY DEFINER`` function that adds 1 and
returns the address, and nothing else from any shop. The address comes from the
synced catalogue, never from the request (§3): a link can only open a page of
the shop that made it.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import metadata, new_id
from neura_core.ids import LINK

LINKS = "links"
LINK_CLICKS = "link_clicks"
#: The one statement :meth:`Database.follow_session` may make (ADR-0074 §7).
FOLLOW_FUNCTION = "neura_follow_link"

#: A code: 6 characters from lower-case letters and digits, without the
#: look-alikes ``0``, ``o``, ``1`` and ``l`` (ADR-0074 §2).
CODE_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
CODE_LENGTH = 6
#: A new code that is already taken is drawn again, this many times at most.
CODE_TRIES = 5
#: An own link's name (*Tuesday post*), as an own date's.
MAX_NAME_CHARS = 60
_CODE = re.compile(rf"^[{CODE_ALPHABET}]{{{CODE_LENGTH}}}$")


class Place(StrEnum):
    """Where the owner posts a link: its ``utm_source`` (ADR-0074 §4)."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    #: *Somewhere else*, on *Make a link* only.
    OTHER = "other"


class Post(StrEnum):
    """Which draft of a plan a link belongs to: its ``utm_content``."""

    TEASER = "teaser"
    LAUNCH = "launch"
    LAST_CHANCE = "last_chance"
    EMAIL = "email"


#: The places each post has a link for (R111, R112): a social post one per
#: place, the email one, **the banner none** (whoever sees it is already in
#: the shop).
POST_PLACES: Mapping[Post, tuple[Place, ...]] = {
    Post.TEASER: (Place.FACEBOOK, Place.INSTAGRAM, Place.WHATSAPP),
    Post.LAUNCH: (Place.FACEBOOK, Place.INSTAGRAM, Place.WHATSAPP),
    Post.LAST_CHANCE: (Place.FACEBOOK, Place.INSTAGRAM, Place.WHATSAPP),
    Post.EMAIL: (Place.EMAIL,),
}

#: One row per link. A plan's link names its plan by the date it was made for
#: (``date_key`` and ``day``, as ``calendar_plans``), not by the plan's id: the
#: plan is deleted 30 days after its date and the link is not.
links = Table(
    LINKS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("id", String(64), primary_key=True),
    #: Unique across every shop: the redirect finds a link by it alone.
    Column("code", String(16), nullable=False),
    Column("product_id", String(255), nullable=False),
    #: The product's page when the link was made. The redirect prefers the
    #: catalogue's current one, and falls back to this address's front page.
    Column("url", Text, nullable=False),
    #: The campaign labels, ready to add to the address (ADR-0074 §4).
    Column("labels", Text, nullable=False),
    Column("place", String(16), nullable=False),
    #: A plan's link: the date (``s:<key>`` or ``o:<id>``), its day, the date's
    #: name when the link was made, and the post.
    Column("date_key", String(80), nullable=True),
    Column("day", Date, nullable=True),
    Column("campaign", String(MAX_NAME_CHARS), nullable=True),
    Column("post", String(16), nullable=True),
    #: An own link's name.
    Column("name", String(MAX_NAME_CHARS), nullable=True),
    #: The member of the shop's team who made it.
    Column("created_by", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    #: *Remove*: no longer listed or counted, still forwarding (R113).
    Column("removed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "place IN ('facebook', 'instagram', 'whatsapp', 'email', 'other')", name="place"
    ),
    CheckConstraint(
        "post IS NULL OR post IN ('teaser', 'launch', 'last_chance', 'email')", name="post"
    ),
    CheckConstraint("(post IS NULL) <> (name IS NULL)", name="post_or_name"),
    CheckConstraint(
        "post IS NULL OR (date_key IS NOT NULL AND day IS NOT NULL AND campaign IS NOT NULL)",
        name="post_has_date",
    ),
    Index("uq_links_code", "code", unique=True),
    Index(
        "uq_links_post",
        "tenant_id",
        "date_key",
        "day",
        "post",
        "place",
        "product_id",
        unique=True,
        postgresql_where=text("post IS NOT NULL AND removed_at IS NULL"),
    ),
)

#: One number per link per day (UTC), and nothing about who tapped.
link_clicks = Table(
    LINK_CLICKS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("link_id", String(64), primary_key=True),
    Column("day", Date, primary_key=True),
    Column("clicks", Integer, nullable=False),
)


# ── The code and the labels ──────────────────────────────────────────────────


def new_code() -> str:
    """A fresh random code. Uniqueness is the database's to enforce."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def is_code(value: str) -> bool:
    """Could ``value`` be a code? Anything else is refused before the database."""
    return bool(_CODE.match(value))


def slug(value: str) -> str:
    """``Avurudu`` → ``avurudu``, ``Tuesday post`` → ``tuesday-post``."""
    cut = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cut[:MAX_NAME_CHARS].strip("-") or "link"


def campaign_labels(*, campaign: str, day: date, post: Post, place: Place) -> str:
    """A plan's link's labels: the date and year, and the post (ADR-0074 §4)."""
    return urlencode(
        {
            "utm_source": place.value,
            "utm_medium": _medium(place),
            "utm_campaign": f"{slug(campaign)}-{day.year}",
            "utm_content": post.value.replace("_", "-"),
        }
    )


def own_labels(*, name: str, place: Place) -> str:
    """An own link's labels: its name as the campaign, no ``utm_content``."""
    return urlencode(
        {"utm_source": place.value, "utm_medium": _medium(place), "utm_campaign": slug(name)}
    )


def _medium(place: Place) -> str:
    if place is Place.EMAIL:
        return "email"
    if place is Place.OTHER:
        return "other"
    return "social"


# ── Robots (ADR-0074 §5, as G117) ────────────────────────────────────────────

#: Fetchers that draw a link's preview, search engines, and scripts. Matched in
#: the lower-cased browser name; the name is read here and never stored.
_ROBOT_NAMES = (
    "facebookexternalhit",
    "facebookcatalog",
    "meta-externalagent",
    "twitterbot",
    "slackbot",
    "telegrambot",
    "discordbot",
    "linkedinbot",
    "skypeuripreview",
    "pinterestbot",
    "googlebot",
    "google-inspectiontool",
    "bingbot",
    "applebot",
    "yandex",
    "baiduspider",
    "duckduckbot",
    "petalbot",
    "embedly",
    "crawler",
    "spider",
    "bot/",
    "bot;",
    "+http",
    "curl/",
    "wget/",
    "python-",
    "go-http-client",
)


def is_robot(user_agent: str | None) -> bool:
    """A request that should be forwarded and not counted.

    WhatsApp's preview fetcher calls itself ``WhatsApp/2.x`` with nothing else;
    a person's browser always says ``Mozilla``. An empty name is not a person's
    browser either. **A robot that does not say what it is still counts**, and
    the page says a click is a tap, not a person.
    """
    name = (user_agent or "").strip().lower()
    if not name or name.startswith("whatsapp/"):
        return True
    return any(robot in name for robot in _ROBOT_NAMES)


# ── Reading and writing ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Link:
    """One row of ``links``, with its clicks when they were asked for."""

    id: str
    code: str
    product_id: str
    url: str
    place: Place
    post: Post | None
    date_key: str | None
    day: date | None
    campaign: str | None
    name: str | None
    created_by: str
    created_at: datetime
    removed_at: datetime | None
    clicks: int = 0


def _link(row: Any, clicks: int = 0) -> Link:
    return Link(
        id=row.id,
        code=row.code,
        product_id=row.product_id,
        url=row.url,
        place=Place(row.place),
        post=Post(row.post) if row.post else None,
        date_key=row.date_key,
        day=row.day,
        campaign=row.campaign,
        name=row.name,
        created_by=row.created_by,
        created_at=row.created_at,
        removed_at=row.removed_at,
        clicks=clicks,
    )


@dataclass(frozen=True, slots=True)
class PostClicks:
    """What a plan's page shows under one post (board 80)."""

    #: The product its newest link opens: the chooser starts there. ``None``:
    #: no link copied yet, so the chooser starts on the plan's first product.
    product_id: str | None
    #: Clicks per place, every product's link added together.
    clicks: Mapping[Place, int]


class LinkRepository:
    """Every read and write of the two tables, under the shop's own RLS."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_post(
        self,
        tenant_id: str,
        *,
        date_key: str,
        day: date,
        campaign: str,
        post: Post,
        place: Place,
        product_id: str,
        url: str,
        by: str,
    ) -> Link:
        """A plan's link: the one already made for this post, place and product,
        or a new one (made on the first *Copy*, ADR-0074 §2)."""
        if place not in POST_PLACES[post]:
            raise ValueError(f"{post.value} has no {place.value} link")
        values = {
            "product_id": product_id,
            "url": url,
            "labels": campaign_labels(campaign=campaign, day=day, post=post, place=place),
            "place": place.value,
            "date_key": date_key,
            "day": day,
            "campaign": campaign,
            "post": post.value,
            "created_by": by,
        }
        for _ in range(CODE_TRIES):
            found = await self._post_link(
                tenant_id, date_key=date_key, day=day, post=post, place=place, product_id=product_id
            )
            if found is not None:
                return found
            made = await self._insert(tenant_id, values)
            if made is not None:
                return made
        raise RuntimeError("no free link code")  # pragma: no cover

    async def make_own(
        self, tenant_id: str, *, name: str, place: Place, product_id: str, url: str, by: str
    ) -> Link:
        """An own link (D18). Two links may share a name: the owner tells them apart."""
        values = {
            "product_id": product_id,
            "url": url,
            "labels": own_labels(name=name, place=place),
            "place": place.value,
            "name": name,
            "created_by": by,
        }
        for _ in range(CODE_TRIES):
            made = await self._insert(tenant_id, values)
            if made is not None:
                return made
        raise RuntimeError("no free link code")  # pragma: no cover

    async def _insert(self, tenant_id: str, values: Mapping[str, Any]) -> Link | None:
        """``None`` when the code was taken, or the same post link was just made."""
        row = (
            await self._session.execute(
                pg_insert(links)
                .values(tenant_id=tenant_id, id=new_id(LINK), code=new_code(), **values)
                .on_conflict_do_nothing()
                .returning(links)
            )
        ).first()
        return None if row is None else _link(row)

    async def _post_link(
        self,
        tenant_id: str,
        *,
        date_key: str,
        day: date,
        post: Post,
        place: Place,
        product_id: str,
    ) -> Link | None:
        row = (
            await self._session.execute(
                select(links).where(
                    links.c.tenant_id == tenant_id,
                    links.c.date_key == date_key,
                    links.c.day == day,
                    links.c.post == post.value,
                    links.c.place == place.value,
                    links.c.product_id == product_id,
                    links.c.removed_at.is_(None),
                )
            )
        ).first()
        return None if row is None else _link(row)

    async def listed(self, tenant_id: str) -> list[Link]:
        """Every link not removed, with its clicks, the newest first (board 81)."""
        totals = (
            select(link_clicks.c.link_id, func.sum(link_clicks.c.clicks).label("clicks"))
            .where(link_clicks.c.tenant_id == tenant_id)
            .group_by(link_clicks.c.link_id)
            .subquery()
        )
        result = await self._session.execute(
            select(links, func.coalesce(totals.c.clicks, 0).label("total"))
            .outerjoin(totals, totals.c.link_id == links.c.id)
            .where(links.c.tenant_id == tenant_id, links.c.removed_at.is_(None))
            .order_by(links.c.created_at.desc(), links.c.id.desc())
        )
        return [_link(row, int(row.total)) for row in result.all()]

    async def plan_posts(
        self, tenant_id: str, *, date_key: str, day: date
    ) -> dict[Post, PostClicks]:
        """Each post's chooser and clicks, for one plan's page (board 80)."""
        found = [
            link
            for link in await self.listed(tenant_id)
            if link.post is not None and link.date_key == date_key and link.day == day
        ]
        posts: dict[Post, PostClicks] = {}
        for post in POST_PLACES:
            mine = [link for link in found if link.post is post]
            clicks = dict.fromkeys(POST_PLACES[post], 0)
            for link in mine:
                clicks[link.place] = clicks.get(link.place, 0) + link.clicks
            # `listed` is newest first, so the first is the newest.
            posts[post] = PostClicks(product_id=mine[0].product_id if mine else None, clicks=clicks)
        return posts

    async def remove(self, tenant_id: str, link_id: str, *, at: datetime) -> bool:
        """*Remove*: its clicks go, the link keeps forwarding uncounted (R113)."""
        removed = await self._session.scalar(
            update(links)
            .where(
                links.c.tenant_id == tenant_id,
                links.c.id == link_id,
                links.c.removed_at.is_(None),
            )
            .values(removed_at=at)
            .returning(links.c.id)
        )
        if removed is None:
            return False
        await self._session.execute(
            delete(link_clicks).where(
                link_clicks.c.tenant_id == tenant_id, link_clicks.c.link_id == link_id
            )
        )
        return True


async def follow(session: AsyncSession, code: str, *, count: bool) -> str | None:
    """Where a tap on ``code`` goes, adding 1 to today's count when ``count``.

    Through ``neura_follow_link()``, the one statement that may look across
    shops (ADR-0074 §7); ``session`` is :meth:`Database.follow_session`'s.
    ``None``: no such link, or its shop was removed.
    """
    if not is_code(code):
        return None
    address = await session.scalar(
        text(f"SELECT {FOLLOW_FUNCTION}(:code, :count)"), {"code": code, "count": count}
    )
    return str(address) if address else None


def short_link(base_url: str, code: str) -> str:
    """The address the owner copies: ``https://go.fiveneurals.com/k7m2qa``."""
    return f"{base_url.rstrip('/')}/{code}"


def by_place(values: Sequence[Link]) -> dict[Place, int]:
    """Clicks per place, added together."""
    totals: dict[Place, int] = {}
    for link in values:
        totals[link.place] = totals.get(link.place, 0) + link.clicks
    return totals


__all__ = [
    "CODE_ALPHABET",
    "CODE_LENGTH",
    "FOLLOW_FUNCTION",
    "LINKS",
    "LINK_CLICKS",
    "MAX_NAME_CHARS",
    "POST_PLACES",
    "Link",
    "LinkRepository",
    "Place",
    "Post",
    "PostClicks",
    "by_place",
    "campaign_labels",
    "follow",
    "is_code",
    "is_robot",
    "link_clicks",
    "links",
    "new_code",
    "own_labels",
    "short_link",
    "slug",
]
