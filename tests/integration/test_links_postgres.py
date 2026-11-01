"""Links that count their clicks, against a real PostgreSQL (ADR-0074).

What only the database can show:

* **A plan's link is made once** (§2): copying the same post, place and product
  again gives the same link; another place or product, another link; a link
  removed and copied again, a new one.
* **A tap** (``neura_follow_link``, §3 to §5): adds 1 to today, or nothing for
  a robot (``count`` false); sends the shopper to the product's page **as the
  catalogue has it now**, with the labels before any ``#part``; to the shop's
  front page when the product is gone; nowhere for a code nobody made.
* **Remove** (R113): the clicks go, the link keeps forwarding and stops counting.
* **Isolation** (§7): the follow session sees no row of any table; another
  shop's links and clicks are invisible. That shop removal knows both tables
  (G76) is held by ``test_tenant_drop_postgres.py``.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import delete, func, insert, select, text, update

from neura_agent_core.links import (
    LinkRepository,
    Place,
    Post,
    follow,
    link_clicks,
    links,
)
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_database, get_settings

pytestmark = pytest.mark.integration

TENANT_A = "tn_lnk_a"
TENANT_B = "tn_lnk_b"
BY = "usr_owner"
DAY = date(2027, 4, 14)
DATE_KEY = "s:avurudu"
TEA = "https://shop.example/p/4"


@pytest.fixture
async def db():
    get_settings.cache_clear()
    get_database.cache_clear()
    database = Database.from_settings()
    if not await database.ping():
        await database.dispose()
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    await _purge(database)
    for tenant_id in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant_id) as session:
            for external_id, url in (
                ("4", TEA),
                ("7", "https://shop.example/p/7?variant=2#reviews"),
            ):
                await session.execute(
                    insert(synced_entities).values(
                        tenant_id=tenant_id,
                        platform="generic",
                        entity_type="product",
                        external_id=external_id,
                        neura_id=f"nr_{tenant_id}_{external_id}",
                        fingerprint="f" * 32,
                        document={"title": f"Product {external_id}", "url": url},
                    )
                )
    try:
        yield database
    finally:
        await _purge(database)
        await database.dispose()


async def _purge(database: Database) -> None:
    for tenant_id in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant_id) as session:
            for table in (link_clicks, links, synced_entities):
                await session.execute(delete(table))


async def _post_link(database: Database, tenant_id: str = TENANT_A, **changes):
    values = {
        "date_key": DATE_KEY,
        "day": DAY,
        "campaign": "Avurudu",
        "post": Post.TEASER,
        "place": Place.FACEBOOK,
        "product_id": "4",
        "url": TEA,
        "by": BY,
    } | changes
    async with database.tenant_session(tenant_id) as session:
        return await LinkRepository(session).for_post(tenant_id, **values)


async def _tap(database: Database, code: str, *, count: bool = True) -> str | None:
    async with database.follow_session() as session:
        return await follow(session, code, count=count)


async def _clicks(database: Database, tenant_id: str = TENANT_A) -> int:
    async with database.tenant_session(tenant_id) as session:
        return int(await session.scalar(select(func.coalesce(func.sum(link_clicks.c.clicks), 0))))


# ── Made once ────────────────────────────────────────────────────────────────


async def test_copying_the_same_post_again_gives_the_same_link(db: Database) -> None:
    first = await _post_link(db)
    again = await _post_link(db)
    assert again.id == first.id and again.code == first.code

    other_place = await _post_link(db, place=Place.WHATSAPP)
    other_product = await _post_link(db, product_id="7", url="https://shop.example/p/7")
    assert len({first.code, other_place.code, other_product.code}) == 3


async def test_a_post_has_only_its_own_places(db: Database) -> None:
    with pytest.raises(ValueError, match="email"):
        await _post_link(db, post=Post.TEASER, place=Place.EMAIL)
    with pytest.raises(ValueError, match="facebook"):
        await _post_link(db, post=Post.EMAIL, place=Place.FACEBOOK)


async def test_a_removed_link_copied_again_is_a_new_link(db: Database) -> None:
    first = await _post_link(db)
    async with db.tenant_session(TENANT_A) as session:
        assert await LinkRepository(session).remove(TENANT_A, first.id, at=datetime.now(UTC))
    again = await _post_link(db)
    assert again.id != first.id and again.code != first.code


# ── A tap ────────────────────────────────────────────────────────────────────


async def test_a_tap_counts_and_sends_the_shopper_to_the_product_with_the_labels(
    db: Database,
) -> None:
    link = await _post_link(db)
    address = await _tap(db, link.code)
    assert address is not None
    parts = urlsplit(address)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == TEA
    assert parse_qs(parts.query) == {
        "utm_source": ["facebook"],
        "utm_medium": ["social"],
        "utm_campaign": ["avurudu-2027"],
        "utm_content": ["teaser"],
    }
    await _tap(db, link.code)
    assert await _clicks(db) == 2


async def test_a_robot_is_sent_on_and_not_counted(db: Database) -> None:
    link = await _post_link(db)
    assert await _tap(db, link.code, count=False)
    assert await _clicks(db) == 0


async def test_the_labels_keep_the_address_own_query_and_go_before_its_part(db: Database) -> None:
    link = await _post_link(db, product_id="7", url="https://shop.example/p/7")
    address = await _tap(db, link.code)
    assert address is not None
    assert address.startswith("https://shop.example/p/7?variant=2&utm_source=facebook&")
    assert address.endswith("utm_content=teaser#reviews")


async def test_the_address_is_the_catalogue_s_now(db: Database) -> None:
    link = await _post_link(db)
    async with db.tenant_session(TENANT_A) as session:
        await session.execute(
            update(synced_entities)
            .where(synced_entities.c.external_id == "4")
            .values(document={"title": "Product 4", "url": "https://shop.example/tea-400g"})
        )
    address = await _tap(db, link.code)
    assert address is not None and address.startswith("https://shop.example/tea-400g?utm_source=")


async def test_a_product_gone_from_the_catalogue_opens_the_front_page(db: Database) -> None:
    link = await _post_link(db)
    async with db.tenant_session(TENANT_A) as session:
        await session.execute(delete(synced_entities).where(synced_entities.c.external_id == "4"))
    address = await _tap(db, link.code)
    assert address is not None and address.startswith("https://shop.example/?utm_source=facebook")
    assert await _clicks(db) == 1


async def test_a_catalogue_address_that_is_not_a_web_page_is_never_followed(db: Database) -> None:
    link = await _post_link(db)
    async with db.tenant_session(TENANT_A) as session:
        await session.execute(
            update(synced_entities)
            .where(synced_entities.c.external_id == "4")
            .values(document={"title": "Product 4", "url": "javascript:alert(1)"})
        )
    address = await _tap(db, link.code)
    assert address is not None and address.startswith("https://shop.example/?")


async def test_a_code_nobody_made_goes_nowhere(db: Database) -> None:
    assert await _tap(db, "zzzzzz") is None
    assert await _tap(db, "../../etc/passwd") is None


# ── Remove ───────────────────────────────────────────────────────────────────


async def test_remove_deletes_the_clicks_and_keeps_the_link_forwarding(db: Database) -> None:
    link = await _post_link(db)
    await _tap(db, link.code)
    async with db.tenant_session(TENANT_A) as session:
        repository = LinkRepository(session)
        assert await repository.remove(TENANT_A, link.id, at=datetime.now(UTC))
        assert not await repository.remove(TENANT_A, link.id, at=datetime.now(UTC))
        assert await repository.listed(TENANT_A) == []
    assert await _clicks(db) == 0
    assert await _tap(db, link.code)
    assert await _clicks(db) == 0


# ── The lists ────────────────────────────────────────────────────────────────


async def test_the_list_is_newest_first_with_each_link_s_clicks(db: Database) -> None:
    post = await _post_link(db)
    async with db.tenant_session(TENANT_A) as session:
        own = await LinkRepository(session).make_own(
            TENANT_A, name="Tuesday post", place=Place.FACEBOOK, product_id="7", url=TEA, by=BY
        )
    for _ in range(3):
        await _tap(db, own.code)
    await _tap(db, post.code)
    async with db.tenant_session(TENANT_A) as session:
        listed = await LinkRepository(session).listed(TENANT_A)
    assert [(link.code, link.clicks) for link in listed] == [(own.code, 3), (post.code, 1)]
    assert listed[0].name == "Tuesday post" and listed[0].post is None
    assert listed[1].post is Post.TEASER and listed[1].campaign == "Avurudu"


async def test_a_plan_s_posts_show_the_newest_product_and_clicks_per_place(db: Database) -> None:
    facebook = await _post_link(db)
    whatsapp = await _post_link(db, place=Place.WHATSAPP)
    await _post_link(db, place=Place.FACEBOOK, product_id="7", url="https://shop.example/p/7")
    email = await _post_link(db, post=Post.EMAIL, place=Place.EMAIL)
    for code in (facebook.code, facebook.code, whatsapp.code, email.code):
        await _tap(db, code)
    # Another date's link is not this plan's.
    await _tap(db, (await _post_link(db, day=date(2027, 5, 31))).code)

    async with db.tenant_session(TENANT_A) as session:
        posts = await LinkRepository(session).plan_posts(TENANT_A, date_key=DATE_KEY, day=DAY)
    assert posts[Post.TEASER].product_id == "7"
    assert dict(posts[Post.TEASER].clicks) == {
        Place.FACEBOOK: 2,
        Place.INSTAGRAM: 0,
        Place.WHATSAPP: 1,
    }
    assert dict(posts[Post.EMAIL].clicks) == {Place.EMAIL: 1}
    assert posts[Post.LAUNCH].product_id is None
    assert sum(posts[Post.LAUNCH].clicks.values()) == 0


# ── Isolation ────────────────────────────────────────────────────────────────


async def test_the_follow_session_sees_no_row_of_any_table(db: Database) -> None:
    await _post_link(db)
    async with db.follow_session() as session:
        assert await session.scalar(select(func.count()).select_from(links)) == 0
        assert await session.scalar(select(func.count()).select_from(link_clicks)) == 0
        assert await session.scalar(select(func.count()).select_from(synced_entities)) == 0


async def test_another_shop_s_links_and_clicks_are_invisible(db: Database) -> None:
    link = await _post_link(db)
    await _tap(db, link.code)
    async with db.tenant_session(TENANT_B) as session:
        assert await LinkRepository(session).listed(TENANT_B) == []
        assert await LinkRepository(session).listed(TENANT_A) == []
        assert not await LinkRepository(session).remove(TENANT_A, link.id, at=datetime.now(UTC))
    assert await _clicks(db, TENANT_B) == 0
    assert await _clicks(db, TENANT_A) == 1


async def test_two_shops_never_share_a_code(db: Database) -> None:
    a = await _post_link(db)
    b = await _post_link(db, TENANT_B)
    assert a.code != b.code
    async with db.follow_session() as session:
        rows = await session.execute(
            text("SELECT neura_follow_link(:code, false)"), {"code": a.code}
        )
        assert str(rows.scalar()).startswith(TEA)
