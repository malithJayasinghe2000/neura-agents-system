"""GROW's *Missing from your pages* data against a real PostgreSQL (ADR-0064).

What only the database can show:

* **The grouping rules** (R40, R43): one topic per product and label, counted by
  *different conversations*, shown from 2; the most recent question is the one
  shown; only the last 30 days count.
* **I added it**: the topic leaves the list, and comes back only when 2 more
  shoppers ask it after that moment.
* **One row per reply**: the nightly scan may meet a reply twice and must not
  count it twice.
* **Isolation**: another shop's gaps are invisible (row-level security).
* **Deletion with the chat**: a gap goes when its conversation expires
  (ADR-0042 §3). That shop removal knows the new tables (G76) is held by
  ``test_tenant_drop_postgres.py``, which compares its list with the database.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from neura_agent_core.conversations import (
    ConversationRepository,
    ConversationState,
    conversation_messages,
    conversations,
)
from neura_agent_core.gaps import (
    GapKind,
    PageGap,
    PageGapRepository,
    page_gap_fixes,
    page_gap_scans,
    page_gaps,
)
from neura_core import Database, get_database, get_settings

pytestmark = pytest.mark.integration

TENANT_A = "tn_igap_a"
TENANT_B = "tn_igap_b"
NOW = datetime.now(UTC)
SINCE = NOW - timedelta(days=30)


@pytest.fixture
async def db():
    get_settings.cache_clear()
    get_database.cache_clear()
    database = Database.from_settings()
    if not await database.ping():
        await database.dispose()
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    await _purge(database)
    try:
        yield database
    finally:
        await _purge(database)
        await database.dispose()


async def _purge(database: Database) -> None:
    for tenant_id in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant_id) as session:
            for table in (
                page_gaps,
                page_gap_fixes,
                page_gap_scans,
                conversation_messages,
                conversations,
            ):
                await session.execute(delete(table))


def _gap(
    conversation: str,
    message: str,
    *,
    product: str | None = "5",
    fact: str = "organic",
    question: str = "Is it organic?",
    age: timedelta = timedelta(days=1),
    kind: GapKind = GapKind.HALF_ANSWERED,
) -> PageGap:
    return PageGap(
        conversation_id=conversation,
        message_id=message,
        kind=kind,
        product_id=product,
        fact=fact,
        question=question,
        asked_at=NOW - age,
        prompt_revision="test",
    )


async def _record(database: Database, tenant_id: str, *gaps: PageGap) -> list[bool]:
    async with database.tenant_session(tenant_id) as session:
        repository = PageGapRepository(session)
        return [await repository.record(tenant_id, gap) for gap in gaps]


async def _topics(database: Database, tenant_id: str) -> list:  # type: ignore[type-arg]
    async with database.tenant_session(tenant_id) as session:
        return await PageGapRepository(session).topics(tenant_id, since=SINCE)


async def test_two_different_shoppers_make_a_topic(db: Database) -> None:
    await _record(
        db,
        TENANT_A,
        _gap("cnv_1", "msg_1", question="is this tea organic?", age=timedelta(days=3)),
        _gap("cnv_2", "msg_2", question="Is it organic?", age=timedelta(days=1)),
    )
    [topic] = await _topics(db, TENANT_A)
    assert (topic.product_id, topic.fact, topic.shoppers) == ("5", "organic", 2)
    assert topic.question == "Is it organic?"  # the most recent
    assert abs((topic.last_asked - (NOW - timedelta(days=1))).total_seconds()) < 1


async def test_one_shopper_asking_twice_is_not_enough(db: Database) -> None:
    await _record(db, TENANT_A, _gap("cnv_1", "msg_1"), _gap("cnv_1", "msg_2"))
    assert await _topics(db, TENANT_A) == []


async def test_only_the_last_30_days_count(db: Database) -> None:
    await _record(
        db,
        TENANT_A,
        _gap("cnv_1", "msg_1", age=timedelta(days=31)),
        _gap("cnv_2", "msg_2", age=timedelta(days=2)),
    )
    assert await _topics(db, TENANT_A) == []


async def test_a_shop_fact_has_no_product(db: Database) -> None:
    await _record(
        db,
        TENANT_A,
        _gap("cnv_1", "msg_1", product=None, fact="cash on delivery", question="Cash on delivery?"),
        _gap("cnv_2", "msg_2", product=None, fact="cash on delivery", question="Can I pay cash?"),
    )
    [topic] = await _topics(db, TENANT_A)
    assert topic.product_id is None
    assert topic.shoppers == 2


async def test_most_asked_first(db: Database) -> None:
    await _record(
        db,
        TENANT_A,
        _gap("cnv_1", "msg_1", fact="caffeine", question="Caffeine?"),
        _gap("cnv_2", "msg_2", fact="caffeine", question="Caffeine?"),
        _gap("cnv_3", "msg_3"),
        _gap("cnv_4", "msg_4"),
        _gap("cnv_5", "msg_5"),
    )
    assert [t.fact for t in await _topics(db, TENANT_A)] == ["organic", "caffeine"]


async def test_a_reply_is_counted_once(db: Database) -> None:
    assert await _record(db, TENANT_A, _gap("cnv_1", "msg_1"), _gap("cnv_1", "msg_1")) == [
        True,
        False,
    ]


async def test_i_added_it_hides_the_topic_until_two_more_ask(db: Database) -> None:
    await _record(db, TENANT_A, _gap("cnv_1", "msg_1"), _gap("cnv_2", "msg_2"))
    async with db.tenant_session(TENANT_A) as session:
        await PageGapRepository(session).mark_fixed(
            TENANT_A, product_id="5", fact="organic", by="usr_owner"
        )
    assert await _topics(db, TENANT_A) == []

    later = NOW + timedelta(minutes=5)
    await _record(db, TENANT_A, _gap("cnv_3", "msg_3", age=-timedelta(minutes=5)))
    assert await _topics(db, TENANT_A) == [], "one shopper after the fix is not enough"

    await _record(db, TENANT_A, _gap("cnv_4", "msg_4", age=-timedelta(minutes=6)))
    [topic] = await _topics(db, TENANT_A)
    assert topic.shoppers == 2, "only the shoppers who asked after the fix count"
    assert topic.last_asked > later


async def test_count_matches_the_list(db: Database) -> None:
    await _record(db, TENANT_A, _gap("cnv_1", "msg_1"), _gap("cnv_2", "msg_2"))
    async with db.tenant_session(TENANT_A) as session:
        assert await PageGapRepository(session).count_topics(TENANT_A, since=SINCE) == 1


async def test_another_shop_sees_nothing(db: Database) -> None:
    await _record(db, TENANT_A, _gap("cnv_1", "msg_1"), _gap("cnv_2", "msg_2"))
    assert await _topics(db, TENANT_B) == []


async def test_scanned_until_is_remembered_per_shop(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        repository = PageGapRepository(session)
        assert await repository.scanned_until(TENANT_A) is None
        await repository.set_scanned_until(TENANT_A, NOW)
        await repository.set_scanned_until(TENANT_A, NOW + timedelta(hours=1))
    async with db.tenant_session(TENANT_A) as session:
        until = await PageGapRepository(session).scanned_until(TENANT_A)
    assert until is not None
    assert abs((until - (NOW + timedelta(hours=1))).total_seconds()) < 1
    async with db.tenant_session(TENANT_B) as session:
        assert await PageGapRepository(session).scanned_until(TENANT_B) is None


async def test_a_gap_goes_with_its_conversation(db: Database) -> None:
    """ADR-0042 §3: the deletion ships with the storage, in the same change."""
    async with db.tenant_session(TENANT_A) as session:
        repository = ConversationRepository(session)
        for conversation in ("cnv_old", "cnv_new"):
            await repository.start(TENANT_A, conversation_id=conversation, agent_key="care")
            await repository.append_turn(
                TENANT_A,
                conversation,
                shopper="Is it organic?",
                reply="I can't confirm that.",
                state=ConversationState.RESOLVED,
            )
        await session.execute(
            update(conversations)
            .where(conversations.c.id == "cnv_old")
            .values(updated_at=NOW - timedelta(days=100))
        )
    await _record(db, TENANT_A, _gap("cnv_old", "msg_1"), _gap("cnv_new", "msg_2"))

    async with db.tenant_session(TENANT_A) as session:
        await ConversationRepository(session).delete_older_than(TENANT_A, NOW - timedelta(days=90))
    async with db.tenant_session(TENANT_A) as session:
        left = set((await session.execute(select(page_gaps.c.conversation_id))).scalars())
    assert left == {"cnv_new"}, "the old chat's gap went with it, the new one stayed"
