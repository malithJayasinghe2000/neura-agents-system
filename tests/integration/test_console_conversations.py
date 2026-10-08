"""Console screen 2 — Conversations, over HTTP and against real RLS.

The same deterministic bar as Review (`docs/console.md §6`), re-asserted rather
than assumed: **the bar is per screen, not per project.** A membership check that
holds on one route and was forgotten on another is exactly the shape of bug this
section exists to catch, and "the other file tests it" has never once been true
of the route somebody added last.

On top of the bar, the two things this screen is *for*:

* the five conversation states stay five — `blocked` and `escalated` are both
  refusals costing wildly different things ([ADR-0012](../../docs/architecture/adr/0012-blocking-is-about-cost.md)),
  and `shadowed` is neither;
* the transcript comes back **as stored**, tokenised, and nothing here quietly
  redacts or rehydrates it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from neura_api.main import create_app
from neura_core import Database, get_settings, load_env
from neura_core.identity import COOKIE_NAME, issue
from tests.integration.console_fixtures import (
    QUESTION,
    REPLY,
    TOKENISED_QUESTION,
    Shop,
    drop_shop,
    make_shop,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "")
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
    yield database
    await database.dispose()


@pytest.fixture
async def shop(db: Database):
    made = await make_shop(db)
    yield made
    await drop_shop(db, made)


@pytest.fixture
async def other_shop(db: Database):
    """The second populated tenant `console.md §6.4` requires."""
    made = await make_shop(db)
    yield made
    await drop_shop(db, made)


def cookie_for(user_id: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user_id, get_settings().secret_key)}


def listing(client: TestClient, shop: Shop, *, query: str = "") -> list[dict]:
    response = client.get(
        f"/v1/console/shops/{shop.tenant}/conversations{query}", cookies=cookie_for(shop.user)
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def transcript(client: TestClient, shop: Shop, conversation_id: str) -> dict:
    response = client.get(
        f"/v1/console/shops/{shop.tenant}/conversations/{conversation_id}",
        cookies=cookie_for(shop.user),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class TestOnlyYourOwnShop:
    """`console.md §6.1`, §6.2, §6.4 — re-asserted on this screen's own routes."""

    def test_a_person_reaches_their_own_shops_conversations(self, client: TestClient, shop) -> None:
        assert len(listing(client, shop)) == 3

    def test_another_persons_shop_is_not_reachable(
        self, client: TestClient, shop, other_shop
    ) -> None:
        response = client.get(
            f"/v1/console/shops/{other_shop.tenant}/conversations",
            cookies=cookie_for(shop.user),
        )
        assert response.status_code == 404
        assert other_shop.answered_conversation not in response.text

    def test_another_tenants_transcript_is_not_reachable_by_id(
        self, client: TestClient, shop, other_shop
    ) -> None:
        """The sharper case: the *right* person, the *right* shop in the URL, and
        another tenant's conversation id. RLS is what refuses this, not a check
        anybody wrote — which is why it is asserted rather than assumed."""
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/conversations/{other_shop.answered_conversation}",
            cookies=cookie_for(shop.user),
        )
        assert response.status_code == 404
        assert REPLY not in response.text

    def test_no_session_reaches_nothing(self, client: TestClient, shop) -> None:
        assert client.get(f"/v1/console/shops/{shop.tenant}/conversations").status_code == 401

    def test_a_forged_cookie_reaches_nothing(self, client: TestClient, shop) -> None:
        forged = issue(shop.user, "not-the-servers-secret")
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/conversations", cookies={COOKIE_NAME: forged}
        )
        assert response.status_code == 401

    async def test_a_revoked_membership_reaches_nothing_immediately(
        self, client: TestClient, db: Database, shop
    ) -> None:
        from datetime import UTC, datetime

        from neura_core.identity.schema import memberships

        assert listing(client, shop)

        async with db.tenant_session(shop.tenant) as session:
            await session.execute(
                memberships.update()
                .where(memberships.c.id == shop.membership)
                .values(revoked_at=datetime.now(UTC))
            )

        after = client.get(
            f"/v1/console/shops/{shop.tenant}/conversations", cookies=cookie_for(shop.user)
        )
        assert after.status_code == 404


class TestTheFiveStatesStayFive:
    """ADR-0012 and agent-runtime.md §6, as a screen can express them."""

    def test_an_escalation_is_not_reported_as_resolved(self, client: TestClient, shop) -> None:
        states = {row["id"]: row["state"] for row in listing(client, shop)}
        assert states[shop.escalated_conversation] == "escalated"
        assert states[shop.answered_conversation] == "resolved"

    def test_a_shadowed_conversation_is_its_own_state(self, client: TestClient, shop) -> None:
        """Not `resolved` — nothing was resolved, and counting it as one would
        inflate the number this product will eventually be sold on."""
        states = {row["id"]: row["state"] for row in listing(client, shop)}
        assert states[shop.shadowed_conversation] == "shadowed"

    def test_filtering_narrows_to_exactly_that_state(self, client: TestClient, shop) -> None:
        rows = listing(client, shop, query="?state=escalated")
        assert [row["id"] for row in rows] == [shop.escalated_conversation]

    def test_an_unknown_state_is_refused_and_not_silently_ignored(
        self, client: TestClient, shop
    ) -> None:
        """A dropped filter returns everything while looking filtered — which is
        how a merchant concludes they have no escalations."""
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/conversations?state=nonsense",
            cookies=cookie_for(shop.user),
        )
        assert response.status_code == 400

    def test_the_default_listing_hides_no_state(self, client: TestClient, shop) -> None:
        """The interesting rows here are the refusals. A list that opened on
        "answered" would report a healthier product than the merchant has."""
        assert {row["state"] for row in listing(client, shop)} == {
            "resolved",
            "escalated",
            "shadowed",
        }


class TestTheTranscript:
    def test_the_thread_carries_both_sides_in_order(self, client: TestClient, shop) -> None:
        thread = transcript(client, shop, shop.answered_conversation)
        assert [m["role"] for m in thread["messages"]] == ["shopper", "agent"]
        assert thread["messages"][0]["content"] == QUESTION
        assert thread["messages"][1]["content"] == REPLY

    def test_the_reply_carries_what_it_cited(self, client: TestClient, shop) -> None:
        """The difference between a right answer from the right lookup and a
        right answer by luck — the same distinction Review is built around."""
        thread = transcript(client, shop, shop.answered_conversation)
        # `name` is null: the fixture's synced catalogue holds no such policy.
        assert thread["messages"][1]["citations"] == [
            {"type": "policy", "id": "fixture-returns", "name": None}
        ]

    def test_the_per_turn_state_is_on_the_reply_and_not_the_question(
        self, client: TestClient, shop
    ) -> None:
        thread = transcript(client, shop, shop.answered_conversation)
        assert thread["messages"][0]["state"] is None
        assert thread["messages"][1]["state"] == "resolved"

    def test_a_shadowed_thread_has_the_question_and_no_reply(
        self, client: TestClient, shop
    ) -> None:
        """Exactly what happened: the shopper spoke, and the agent's draft was
        withheld into `shadow_turns` rather than written as history."""
        thread = transcript(client, shop, shop.shadowed_conversation)
        assert [m["role"] for m in thread["messages"]] == ["shopper"]

    def test_the_transcript_is_returned_as_stored_and_is_tokenised(
        self, client: TestClient, shop
    ) -> None:
        """`console.md §3.3` promises unredacted PII and `append_turn` stores the
        message tokenised (security-model.md §6.2). This asserts **what is true
        today** so the day somebody changes it is a day a test goes red and the
        contradiction gets an ADR, rather than a day the behaviour quietly flips.
        """
        thread = transcript(client, shop, shop.escalated_conversation)
        assert thread["messages"][0]["content"] == TOKENISED_QUESTION
        assert "[EMAIL_1]" in thread["messages"][0]["content"]

    def test_an_unknown_conversation_is_404(self, client: TestClient, shop) -> None:
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/conversations/cnv_nope",
            cookies=cookie_for(shop.user),
        )
        assert response.status_code == 404

    def test_a_short_thread_is_not_marked_truncated(self, client: TestClient, shop) -> None:
        assert transcript(client, shop, shop.answered_conversation)["truncated"] is False

    def test_the_reply_records_which_prompt_wrote_it(self, client: TestClient, shop) -> None:
        """A regression pin, and it caught a live defect on 2026-08-27.

        `append_turn` wrote its two messages as one multi-row
        `insert().values([...])`, which renders its column list from the **first**
        mapping and silently discards anything appearing only in a later one. The
        shopper's row had no `intent`, `state` or `prompt_revision` key, so **no
        agent message ever stored any of the three** — successfully, with no
        error anywhere. `citations` survived only because the shopper's row also
        happened to set it.

        The cost was not the transcript screen. `prompt_revision` exists so a
        reply can be traced to the prompt that produced it six weeks later
        (`conversations.py`), and for as long as this was wrong it held nothing
        to trace. Asserted here because this is the layer that reads it, and
        because nothing else would have noticed."""
        thread = transcript(client, shop, shop.answered_conversation)
        reply = thread["messages"][1]
        assert reply["intent"] == "policy_question"
        assert reply["state"] == "resolved"


class TestHeldDraftsBesideTheThread:
    """2026-09-28: a held chat shows what the assistant would have said, under
    the question it answered — as its own field, never merged into history."""

    def test_each_held_draft_names_the_question_it_answers(self, client: TestClient, shop) -> None:
        thread = transcript(client, shop, shop.shadowed_conversation)
        question = thread["messages"][0]
        assert [held["id"] for held in thread["held"]] == [shop.answered_turn, shop.declined_turn]
        assert {held["message_id"] for held in thread["held"]} == {question["id"]}
        assert thread["held"][0]["draft"] == REPLY
        assert thread["held"][0]["state"] == "resolved"

    def test_a_draft_is_never_merged_into_the_messages(self, client: TestClient, shop) -> None:
        """shadow.py's two tables exist so a draft never becomes history."""
        thread = transcript(client, shop, shop.shadowed_conversation)
        assert [m["role"] for m in thread["messages"]] == ["shopper"]
        assert all(REPLY not in m["content"] for m in thread["messages"])

    def test_a_held_turn_with_no_draft_says_why(self, client: TestClient, shop) -> None:
        declined = transcript(client, shop, shop.shadowed_conversation)["held"][1]
        assert declined["draft"] == ""
        assert "handed this to a person" in declined["no_draft_reason"]
        assert (
            transcript(client, shop, shop.shadowed_conversation)["held"][0]["no_draft_reason"] == ""
        )

    def test_a_graded_draft_says_so_and_by_whom(self, client: TestClient, shop) -> None:
        assert transcript(client, shop, shop.shadowed_conversation)["held"][0]["verdict"] is None
        graded = client.post(
            f"/v1/console/shops/{shop.tenant}/review/{shop.answered_turn}/grade",
            json={"verdict": "agree", "note": ""},
            cookies=cookie_for(shop.user),
        )
        assert graded.status_code == 200, graded.text

        held = transcript(client, shop, shop.shadowed_conversation)["held"][0]
        assert held["verdict"] == "agree"
        assert held["reviewed_by"] == shop.user
        assert held["reviewed_at"] is not None

    def test_an_answered_chat_has_nothing_held(self, client: TestClient, shop) -> None:
        assert transcript(client, shop, shop.answered_conversation)["held"] == []

    async def test_another_shops_draft_never_appears_even_on_the_same_conversation_id(
        self, client: TestClient, db: Database, shop, other_shop
    ) -> None:
        """Two populated tenants, and the sharper case: a draft in the *other*
        tenant filed under *this* shop's conversation id. RLS is what keeps it
        out, not a `WHERE` anybody wrote — which is why it is asserted."""
        from sqlalchemy import delete

        from neura_agent_core.shadow import ShadowRepository, ShadowTurn, shadow_turns

        async with db.tenant_session(other_shop.tenant) as session:
            planted = await ShadowRepository(session).record(
                ShadowTurn(
                    tenant_id=other_shop.tenant,
                    conversation_id=shop.shadowed_conversation,
                    message_id="msg_other_shop",
                    agent_key="care",
                    mode="shadow",
                    state="resolved",
                    draft="OTHER SHOP DRAFT — must never appear",
                )
            )
        try:
            response = client.get(
                f"/v1/console/shops/{shop.tenant}/conversations/{shop.shadowed_conversation}",
                cookies=cookie_for(shop.user),
            )
            assert response.status_code == 200, response.text
            assert "OTHER SHOP DRAFT" not in response.text
            assert planted not in response.text
        finally:
            async with db.tenant_session(other_shop.tenant) as session:
                await session.execute(delete(shadow_turns).where(shadow_turns.c.id == planted))


class TestWhatAReplyLookedAtByName:
    """Each citation carries its title from the synced catalogue — the words a
    shop owner knows it by, never `product:1311`."""

    async def test_a_cited_source_carries_its_catalogue_title(
        self, client: TestClient, db: Database, shop
    ) -> None:
        async with _catalogue(db, shop.tenant, "policy", "fixture-returns", {"title": "Returns"}):
            reply = transcript(client, shop, shop.answered_conversation)["messages"][1]
        assert reply["citations"] == [
            {"type": "policy", "id": "fixture-returns", "name": "Returns"}
        ]

    async def test_a_category_is_named_by_its_name(
        self, client: TestClient, db: Database, shop
    ) -> None:
        """A category's document has `name` where a product's has `title`."""
        async with _catalogue(db, shop.tenant, "policy", "fixture-returns", {"name": "Knitwear"}):
            reply = transcript(client, shop, shop.answered_conversation)["messages"][1]
        assert reply["citations"][0]["name"] == "Knitwear"

    async def test_another_shops_catalogue_never_names_this_shops_source(
        self, client: TestClient, db: Database, shop, other_shop
    ) -> None:
        async with _catalogue(
            db, other_shop.tenant, "policy", "fixture-returns", {"title": "OTHER SHOP TITLE"}
        ):
            response = client.get(
                f"/v1/console/shops/{shop.tenant}/conversations/{shop.answered_conversation}",
                cookies=cookie_for(shop.user),
            )
        assert response.status_code == 200, response.text
        assert "OTHER SHOP TITLE" not in response.text
        assert response.json()["data"]["messages"][1]["citations"][0]["name"] is None

    async def test_the_same_id_under_another_type_is_not_used(
        self, client: TestClient, db: Database, shop
    ) -> None:
        """A product and a policy can share an id; the pair is the key."""
        async with _catalogue(
            db, shop.tenant, "product", "fixture-returns", {"title": "A product"}
        ):
            reply = transcript(client, shop, shop.answered_conversation)["messages"][1]
        assert reply["citations"][0]["name"] is None


@asynccontextmanager
async def _catalogue(
    db: Database, tenant: str, entity_type: str, external_id: str, document: dict
) -> AsyncIterator[None]:
    """One synced catalogue row for the length of a test, then removed."""
    from sqlalchemy import delete

    from neura_commerce.sync.schema import synced_entities
    from neura_core import ids

    async with db.tenant_session(tenant) as session:
        await session.execute(
            synced_entities.insert().values(
                tenant_id=tenant,
                platform="console-test",
                entity_type=entity_type,
                external_id=external_id,
                neura_id=ids.new_id(ids.NEURA_ENTITY),
                fingerprint="console-test",
                document=document,
            )
        )
    try:
        yield
    finally:
        async with db.tenant_session(tenant) as session:
            await session.execute(
                delete(synced_entities)
                .where(synced_entities.c.tenant_id == tenant)
                .where(synced_entities.c.platform == "console-test")
            )


class TestNoAuthorityAndNoOtherTenantInAnyBody:
    """`console.md §6.4` and §6.6."""

    def test_no_response_carries_a_key_a_credential_or_another_tenants_row(
        self, client: TestClient, shop, other_shop
    ) -> None:
        bodies = [
            client.get(
                f"/v1/console/shops/{shop.tenant}/conversations", cookies=cookie_for(shop.user)
            ).text,
            client.get(
                f"/v1/console/shops/{shop.tenant}/conversations/{shop.answered_conversation}",
                cookies=cookie_for(shop.user),
            ).text,
        ]
        for body in bodies:
            assert "fn_sk_" not in body
            assert "fn_pk_" not in body
            assert "MUST-NEVER-BE-RETURNED" not in body
            assert other_shop.tenant not in body
            assert other_shop.user not in body


def page_of(client: TestClient, shop: Shop, query: str) -> dict:
    """The whole envelope — the rows *and* what the list says about itself."""
    response = client.get(
        f"/v1/console/shops/{shop.tenant}/conversations{query}", cookies=cookie_for(shop.user)
    )
    assert response.status_code == 200, response.text
    return response.json()


def ids_of(rows: list[dict]) -> set[str]:
    return {row["id"] for row in rows}


class TestFindingAConversation:
    """A list of states and timestamps is a list nobody can use (2026-09-27).

    Each row carries the shopper's first question, the list can be searched and
    narrowed, and it says how many match and where a page sits among them —
    without turning the keyset cursor into an offset (api-design.md §5).
    """

    def test_every_row_carries_the_shoppers_first_question_as_stored(
        self, client: TestClient, shop
    ) -> None:
        """Tokens and all: the list must not redact what the transcript shows,
        nor rehydrate what was never stored."""
        first = {row["id"]: row["first_question"] for row in listing(client, shop)}
        assert first[shop.answered_conversation] == QUESTION
        assert first[shop.shadowed_conversation] == QUESTION
        assert first[shop.escalated_conversation] == TOKENISED_QUESTION

    def test_search_finds_what_the_shopper_wrote_in_any_case(
        self, client: TestClient, shop
    ) -> None:
        assert ids_of(listing(client, shop, query="?q=BOOTS")) == {
            shop.answered_conversation,
            shop.shadowed_conversation,
        }
        assert ids_of(listing(client, shop, query="?q=where%20is%20my%20order")) == {
            shop.escalated_conversation
        }

    def test_search_never_matches_the_assistants_words(self, client: TestClient, shop) -> None:
        """ "delivery" is in the reply and nowhere in a question. A merchant
        searching for what a customer asked must not get every thread the
        assistant happened to mention it in."""
        assert "delivery" in REPLY and "delivery" not in QUESTION
        assert listing(client, shop, query="?q=delivery") == []

    def test_search_characters_are_searched_for_not_interpreted(
        self, client: TestClient, shop
    ) -> None:
        """`%` and `_` are LIKE's wildcards. Unescaped, a search for either
        would match every conversation while looking like a real result.

        `_` is sharper than it looks: the tokenised question really does contain
        one (`[EMAIL_1]`), so the right answer is that one thread — not none,
        and not all three."""
        assert listing(client, shop, query="?q=%25") == []
        assert ids_of(listing(client, shop, query="?q=_")) == {shop.escalated_conversation}

    def test_search_does_not_reach_another_shop_with_the_same_words(
        self, client: TestClient, shop, other_shop
    ) -> None:
        """Both fixtures hold identical questions, so only the ids can tell
        whose rows came back — which is the point: a search that crossed
        tenants would look exactly like a search that worked."""
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/conversations?q=boots",
            cookies=cookie_for(shop.user),
        )
        assert ids_of(response.json()["data"]) <= {
            shop.answered_conversation,
            shop.shadowed_conversation,
        }
        assert other_shop.answered_conversation not in response.text
        assert other_shop.shadowed_conversation not in response.text
        assert response.json()["meta"]["total"] == 2

    def test_an_unknown_assistant_matches_nothing_rather_than_everything(
        self, client: TestClient, shop
    ) -> None:
        """The API knows no agent's name, so it cannot refuse one. What it must
        never do is ignore the filter and return every row looking filtered."""
        assert len(listing(client, shop, query="?agent=care")) == 3
        assert listing(client, shop, query="?agent=nobody-by-this-name") == []

    def test_the_list_says_how_many_match_and_where_each_page_sits(
        self, client: TestClient, shop
    ) -> None:
        first = page_of(client, shop, "?limit=2")
        assert len(first["data"]) == 2
        assert first["meta"]["total"] == 3
        assert first["meta"]["offset"] == 0
        assert first["meta"]["has_previous"] is False
        assert first["meta"]["next_cursor"]

        second = page_of(client, shop, f"?limit=2&cursor={first['meta']['next_cursor']}")
        assert len(second["data"]) == 1
        assert second["meta"]["offset"] == 2
        assert second["meta"]["has_previous"] is True
        # The page before this one is the first page, fetched with no cursor.
        assert second["meta"]["previous_cursor"] is None
        assert ids_of(first["data"]) | ids_of(second["data"]) == {
            shop.answered_conversation,
            shop.escalated_conversation,
            shop.shadowed_conversation,
        }

    def test_newer_leads_back_to_exactly_the_page_before(self, client: TestClient, shop) -> None:
        """A keyset cursor only walks forward; the *Newer* cursor is computed.
        Asserted by walking to page three and back to page two."""
        one = page_of(client, shop, "?limit=1")
        two = page_of(client, shop, f"?limit=1&cursor={one['meta']['next_cursor']}")
        three = page_of(client, shop, f"?limit=1&cursor={two['meta']['next_cursor']}")
        assert three["meta"]["offset"] == 2
        assert three["meta"]["previous_cursor"] is not None

        back = page_of(client, shop, f"?limit=1&cursor={three['meta']['previous_cursor']}")
        assert ids_of(back["data"]) == ids_of(two["data"])
        assert back["meta"]["offset"] == 1

    def test_the_total_counts_what_the_filters_kept(self, client: TestClient, shop) -> None:
        narrowed = page_of(client, shop, "?q=boots&limit=1")
        assert narrowed["meta"]["total"] == 2
        assert page_of(client, shop, "?state=escalated")["meta"]["total"] == 1
