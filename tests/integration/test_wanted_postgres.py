"""GROW's *Shoppers asked for* data against a real PostgreSQL (ADR-0068).

What only the database can show:

* **The grouping rules** (ADR-0068 §3): one row per label, counted by
  *different conversations*, shown from 2; the most recent question is the one
  shown; only the last 30 days count.
* **Hide** (R62): the thing leaves the list, and comes back only when 2 more
  shoppers ask for it after that moment.
* **One row per reply**: the nightly scan may meet a reply twice and must not
  count it twice.
* **Isolation**: another shop's rows are invisible (row-level security).
* **Deletion with the chat**: a row goes when its conversation expires
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
from neura_agent_core.wanted import (
    WantedItem,
    WantedRepository,
    wanted_hides,
    wanted_items,
)
from neura_core import Database, get_database, get_settings

pytestmark = pytest.mark.integration

TENANT_A = "tn_iwant_a"
TENANT_B = "tn_iwant_b"
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
            for table in (wanted_items, wanted_hides, conversation_messages, conversations):
                await session.execute(delete(table))


def _item(
    conversation: str,
    message: str,
    *,
    label: str = "matcha",
    question: str = "Do you have matcha?",
    age: timedelta = timedelta(days=1),
) -> WantedItem:
    return WantedItem(
        conversation_id=conversation,
        message_id=message,
        label=label,
        question=question,
        asked_at=NOW - age,
        prompt_revision="test",
    )


async def _record(database: Database, tenant_id: str, *items: WantedItem) -> list[bool]:
    async with database.tenant_session(tenant_id) as session:
        repository = WantedRepository(session)
        return [await repository.record(tenant_id, item) for item in items]


async def _topics(database: Database, tenant_id: str) -> list:  # type: ignore[type-arg]
    async with database.tenant_session(tenant_id) as session:
        return await WantedRepository(session).topics(tenant_id, since=SINCE)


async def test_two_different_shoppers_make_a_row(db: Database) -> None:
    await _record(
        db,
        TENANT_A,
        _item("cnv_1", "msg_1", question="do you sell matcha?", age=timedelta(days=3)),
        _item("cnv_2", "msg_2", question="Do you have matcha?", age=timedelta(days=1)),
    )
    [topic] = await _topics(db, TENANT_A)
    assert (topic.label, topic.shoppers) == ("matcha", 2)
    assert topic.question == "Do you have matcha?"  # the most recent
    assert abs((topic.last_asked - (NOW - timedelta(days=1))).total_seconds()) < 1


async def test_one_shopper_asking_twice_is_not_enough(db: Database) -> None:
    await _record(db, TENANT_A, _item("cnv_1", "msg_1"), _item("cnv_1", "msg_2"))
    assert await _topics(db, TENANT_A) == []


async def test_only_the_last_30_days_count(db: Database) -> None:
    await _record(
        db,
        TENANT_A,
        _item("cnv_1", "msg_1", age=timedelta(days=31)),
        _item("cnv_2", "msg_2", age=timedelta(days=2)),
    )
    assert await _topics(db, TENANT_A) == []


async def test_most_asked_first(db: Database) -> None:
    await _record(
        db,
        TENANT_A,
        _item("cnv_1", "msg_1", label="oolong tea", question="Any oolong?"),
        _item("cnv_2", "msg_2", label="oolong tea", question="Any oolong?"),
        _item("cnv_3", "msg_3"),
        _item("cnv_4", "msg_4"),
        _item("cnv_5", "msg_5"),
    )
    assert [t.label for t in await _topics(db, TENANT_A)] == ["matcha", "oolong tea"]


async def test_a_reply_is_counted_once(db: Database) -> None:
    assert await _record(db, TENANT_A, _item("cnv_1", "msg_1"), _item("cnv_1", "msg_1")) == [
        True,
        False,
    ]


async def test_hide_takes_it_off_until_two_more_ask(db: Database) -> None:
    """R62: A. Hidden, and back only when shoppers ask again after that day."""
    await _record(db, TENANT_A, _item("cnv_1", "msg_1"), _item("cnv_2", "msg_2"))
    async with db.tenant_session(TENANT_A) as session:
        await WantedRepository(session).hide(TENANT_A, label="matcha", by="usr_owner")
    assert await _topics(db, TENANT_A) == []

    later = NOW + timedelta(minutes=5)
    await _record(db, TENANT_A, _item("cnv_3", "msg_3", age=-timedelta(minutes=5)))
    assert await _topics(db, TENANT_A) == [], "one shopper after Hide is not enough"

    await _record(db, TENANT_A, _item("cnv_4", "msg_4", age=-timedelta(minutes=6)))
    [topic] = await _topics(db, TENANT_A)
    assert topic.shoppers == 2, "only the shoppers who asked after Hide count"
    assert topic.last_asked > later


async def test_hide_records_who_pressed_it(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        repository = WantedRepository(session)
        await repository.hide(TENANT_A, label="matcha", by="usr_owner")
        await repository.hide(TENANT_A, label="matcha", by="usr_other")
    async with db.tenant_session(TENANT_A) as session:
        rows = (await session.execute(select(wanted_hides.c.label, wanted_hides.c.hidden_by))).all()
    assert [tuple(row) for row in rows] == [("matcha", "usr_other")]


async def test_count_matches_the_list(db: Database) -> None:
    await _record(db, TENANT_A, _item("cnv_1", "msg_1"), _item("cnv_2", "msg_2"))
    async with db.tenant_session(TENANT_A) as session:
        assert await WantedRepository(session).count_topics(TENANT_A, since=SINCE) == 1


async def test_another_shop_sees_nothing(db: Database) -> None:
    await _record(db, TENANT_A, _item("cnv_1", "msg_1"), _item("cnv_2", "msg_2"))
    assert await _topics(db, TENANT_B) == []


async def test_a_row_goes_with_its_conversation(db: Database) -> None:
    """ADR-0042 §3: the deletion ships with the storage, in the same change."""
    async with db.tenant_session(TENANT_A) as session:
        repository = ConversationRepository(session)
        for conversation in ("cnv_old", "cnv_new"):
            await repository.start(TENANT_A, conversation_id=conversation, agent_key="sell")
            await repository.append_turn(
                TENANT_A,
                conversation,
                shopper="Do you have matcha?",
                reply="I can't find anything matching that.",
                state=ConversationState.RESOLVED,
            )
        await session.execute(
            update(conversations)
            .where(conversations.c.id == "cnv_old")
            .values(updated_at=NOW - timedelta(days=100))
        )
    await _record(db, TENANT_A, _item("cnv_old", "msg_1"), _item("cnv_new", "msg_2"))

    async with db.tenant_session(TENANT_A) as session:
        await ConversationRepository(session).delete_older_than(TENANT_A, NOW - timedelta(days=90))
    async with db.tenant_session(TENANT_A) as session:
        left = set((await session.execute(select(wanted_items.c.conversation_id))).scalars())
    assert left == {"cnv_new"}, "the old chat's row went with it, the new one stayed"


async def test_labels_for_the_model_to_reuse(db: Database) -> None:
    """ADR-0068 §6: *matcha powder* counts with *matcha* when the model is shown it."""
    await _record(
        db,
        TENANT_A,
        _item("cnv_1", "msg_1"),
        _item("cnv_2", "msg_2"),
        _item("cnv_3", "msg_3", label="oolong tea"),
        _item("cnv_4", "msg_4", label="honey", age=timedelta(days=31)),
    )
    async with db.tenant_session(TENANT_A) as session:
        labels = await WantedRepository(session).labels_since(TENANT_A, since=SINCE)
    assert labels == ["matcha", "oolong tea"], "one shopper is enough to be reused; 31 days is not"


async def _hidden(database: Database, tenant_id: str) -> list:  # type: ignore[type-arg]
    async with database.tenant_session(tenant_id) as session:
        return await WantedRepository(session).hidden(tenant_id, since=SINCE)


async def test_the_hidden_list_is_what_would_be_on_the_page(db: Database) -> None:
    """ADR-0070 §1: hidden, 2 shoppers in 30 days counting every ask, not back already."""
    await _record(
        db,
        TENANT_A,
        _item("cnv_1", "msg_1"),
        _item("cnv_2", "msg_2"),
        _item("cnv_3", "msg_3", label="honey", question="Honey?"),  # one shopper
        _item("cnv_4", "msg_4", label="oolong tea", question="Oolong?"),
        _item("cnv_5", "msg_5", label="oolong tea", question="Oolong?"),
    )
    async with db.tenant_session(TENANT_A) as session:
        repository = WantedRepository(session)
        for label in ("matcha", "honey", "oolong tea"):
            await repository.hide(TENANT_A, label=label, by="usr_owner")
    for n in (6, 7):  # oolong comes back by itself: it is on the page, not hidden
        await _record(
            db,
            TENANT_A,
            _item(f"cnv_{n}", f"msg_{n}", label="oolong tea", age=-timedelta(minutes=n)),
        )

    [hidden] = await _hidden(db, TENANT_A)
    assert (hidden.label, hidden.question, hidden.shoppers) == ("matcha", "Do you have matcha?", 2)
    assert hidden.hidden_at is not None
    assert [t.label for t in await _topics(db, TENANT_A)] == ["oolong tea"]
    assert await _hidden(db, TENANT_B) == [], "another shop sees nothing"


async def test_show_again_brings_every_ask_back(db: Database) -> None:
    """ADR-0070 §2: the Hide is forgotten, so the asks before it count again."""
    await _record(db, TENANT_A, _item("cnv_1", "msg_1"), _item("cnv_2", "msg_2"))
    async with db.tenant_session(TENANT_A) as session:
        repository = WantedRepository(session)
        await repository.hide(TENANT_A, label="matcha", by="usr_owner")
        assert await repository.show_again(TENANT_A, label="matcha") is True
        assert await repository.show_again(TENANT_A, label="matcha") is False, "not hidden now"
    [topic] = await _topics(db, TENANT_A)
    assert (topic.label, topic.shoppers) == ("matcha", 2)
    assert await _hidden(db, TENANT_A) == []
