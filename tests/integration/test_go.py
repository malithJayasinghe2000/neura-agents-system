"""ADR-0074 piece 2: a tap on ``/go/{code}``, through the whole app.

* **a person's tap** is counted and sent on with ``302``, ``no-store``, to the
  product's page with the labels, whatever the request says;
* **a robot's** (a link preview) is sent on and not counted;
* **a code nobody made**: a plain page, ``404``, and nothing counted;
* **no cookie** is set, and nothing about the phone reaches the table.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, insert, select

from neura_agent_core.links import LinkRepository, Place, Post, link_clicks, links
from neura_api.main import create_app
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_settings, load_env

pytestmark = pytest.mark.integration

TENANT = "tn_go_a"
TEA = "https://shop.example/p/4"
SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


@pytest.fixture
def client():
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    await _purge(database)
    async with database.tenant_session(TENANT) as session:
        await session.execute(
            insert(synced_entities).values(
                tenant_id=TENANT,
                platform="generic",
                entity_type="product",
                external_id="4",
                neura_id="nr_go_4",
                fingerprint="f" * 32,
                document={"title": "Ceylon Black Tea BOPF 400g", "url": TEA},
            )
        )
    try:
        yield database
    finally:
        await _purge(database)
        await database.dispose()


async def _purge(database: Database) -> None:
    async with database.tenant_session(TENANT) as session:
        for table in (link_clicks, links, synced_entities):
            await session.execute(delete(table))


async def _link(database: Database) -> str:
    async with database.tenant_session(TENANT) as session:
        made = await LinkRepository(session).for_post(
            TENANT,
            date_key="s:avurudu",
            day=date(2027, 4, 14),
            campaign="Avurudu",
            post=Post.TEASER,
            place=Place.FACEBOOK,
            product_id="4",
            url=TEA,
            by="usr_owner",
        )
    return made.code


async def _clicks(database: Database) -> int:
    async with database.tenant_session(TENANT) as session:
        return int(await session.scalar(select(func.coalesce(func.sum(link_clicks.c.clicks), 0))))


async def test_a_persons_tap_is_counted_and_sent_to_the_product(
    client: TestClient, db: Database
) -> None:
    code = await _link(db)
    response = client.get(
        f"/go/{code}?next=https://evil.example/",
        headers={"User-Agent": SAFARI, "Referer": "https://evil.example/"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"].startswith(f"{TEA}?utm_source=facebook&")
    assert "evil" not in response.headers["location"]
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert await _clicks(db) == 1


async def test_a_link_preview_is_sent_on_and_not_counted(client: TestClient, db: Database) -> None:
    code = await _link(db)
    for agent in (
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "WhatsApp/2.23.20.0 A",
    ):
        response = client.get(f"/go/{code}", headers={"User-Agent": agent}, follow_redirects=False)
        assert response.status_code == 302
    assert await _clicks(db) == 0


async def test_a_code_nobody_made_is_a_plain_page(client: TestClient, db: Database) -> None:
    for code in ("zzzzzz", "not-a-code"):
        response = client.get(f"/go/{code}", headers={"User-Agent": SAFARI}, follow_redirects=False)
        assert response.status_code == 404
        assert "This link is no longer active." in response.text
        assert response.headers["cache-control"] == "no-store"
    assert await _clicks(db) == 0


def test_the_route_is_outside_v1_and_not_in_the_api_description() -> None:
    get_settings.cache_clear()
    app = create_app()
    paths = {context.path or "" for context in iter_route_contexts(app.routes)}
    assert "/go/{code}" in paths
    assert "/v1/go/{code}" not in paths
    assert "/go/{code}" not in app.openapi()["paths"]
