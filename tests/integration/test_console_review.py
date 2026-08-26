"""Console screen 3 — Review, over HTTP and against real Row-Level Security.

Integration rather than unit for the reason `test_console_auth.py` gives: the
interesting assertions here are about what the *database* enforces, and a test
that stubbed it would prove the stub.

**`docs/console.md §6` is the checklist this file exists to satisfy.** That
section writes out the console's own minimum bar, because Rule 4 — *nothing
merges without an eval* — has no obvious meaning for a surface with no model of
ours in it, which is open question **E8** and not a new question. Until E8 is
answered the bar is deterministic and testable, and every clause of it is a
class below:

1. a person reaches **only** the tenants they hold a live membership for;
2. a **revoked** membership reaches nothing, immediately;
4. **no console response ever contains another tenant's row** — asserted with
   two tenants populated, not one;
6. no credential and no API key appears in any response body.

Clauses 3 and 5 are about sign-in itself and are covered in
`test_console_auth.py`, which owns them.

On top of the bar, the three rules `console.md §3.2` sets for this screen —
evidence, withheld turns, no sampling — because a screen that satisfied the
security bar and hid the declines would still be the wrong screen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from neura_agent_core.conversations import (
    ConversationRepository,
    conversation_messages,
    conversations,
)
from neura_agent_core.rag.schema import document_chunks
from neura_agent_core.shadow import ShadowRepository, ShadowTurn, shadow_turns
from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import login_tokens, memberships, users

pytestmark = pytest.mark.integration


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """A client that cannot send email — see `test_console_auth.py` for why."""
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


async def _make_shop(db: Database) -> dict[str, str]:
    """One merchant, one owner, and one shadowed turn with real evidence behind it.

    Built through the ordinary repositories rather than by hand-writing rows, so
    what the queue reads is the shape the turn service actually records.
    """
    made = {
        "user": ids.new_id(ids.USER),
        "tenant": ids.new_id(ids.TENANT),
        "membership": ids.new_id(ids.MEMBERSHIP),
        "conversation": ids.new_id(ids.CONVERSATION),
        "chunk": ids.new_id(ids.CHUNK),
    }
    made["email"] = f"{made['user']}@example.com"

    async with db.identity_session() as s:
        await s.execute(users.insert().values(id=made["user"], email=made["email"], name="Owner"))
    async with db.tenant_session(made["tenant"]) as s:
        await s.execute(
            memberships.insert().values(
                id=made["membership"],
                tenant_id=made["tenant"],
                user_id=made["user"],
                role="owner",
            )
        )

    async with db.tenant_session(made["tenant"]) as s:
        conversations = ConversationRepository(s)
        await conversations.start(
            made["tenant"], conversation_id=made["conversation"], agent_key="care"
        )
        # The shopper's words are history even on a shadowed turn — they
        # genuinely were said. The reply is what is withheld.
        message_id = await conversations.append_shopper_message(
            made["tenant"], made["conversation"], shopper="can I return these after 20 days?"
        )
        made["message"] = message_id

        await s.execute(
            document_chunks.insert().values(
                id=made["chunk"],
                tenant_id=made["tenant"],
                embedding_model="test",
                dimensions=3,
                # pgvector wants its text form, which is what the real store
                # writes too (`rag/postgres._to_vector`). The value is
                # irrelevant here — nothing in this file searches.
                embedding="[0,0,0]",
                content="Returns are accepted within 30 days of delivery.",
                content_hash="hash",
                source_type="policy",
                source_id="returns",
                chunk_index=0,
            )
        )

        shadow = ShadowRepository(s)
        made["answered"] = await shadow.record(
            ShadowTurn(
                tenant_id=made["tenant"],
                conversation_id=made["conversation"],
                message_id=message_id,
                agent_key="care",
                mode="shadow",
                state="resolved",
                intent="policy_question",
                draft="Yes — returns are accepted within 30 days of delivery.",
                grounded=True,
                citations=[
                    {"type": "policy", "id": "returns"},
                    {"type": "tool", "id": "get_order"},
                ],
                tools=["get_order"],
                cost_usd=Decimal("0"),
                latency_ms=1200,
            )
        )
        # The interesting one: the agent declined. ADR-0020's merchant-facing
        # case, and the row a lazy queue would omit.
        made["declined"] = await shadow.record(
            ShadowTurn(
                tenant_id=made["tenant"],
                conversation_id=made["conversation"],
                message_id=message_id,
                agent_key="care",
                mode="shadow",
                state="escalated",
                draft="",
                escalated=True,
                grounded=False,
                verify_reason="the draft claimed a refund window the policy does not state",
            )
        )

    return made


async def _drop_shop(db: Database, made: dict[str, str]) -> None:
    async with db.tenant_session(made["tenant"]) as s:
        await s.execute(delete(shadow_turns).where(shadow_turns.c.tenant_id == made["tenant"]))
        await s.execute(
            delete(document_chunks).where(document_chunks.c.tenant_id == made["tenant"])
        )
        await s.execute(
            delete(conversation_messages).where(conversation_messages.c.tenant_id == made["tenant"])
        )
        await s.execute(delete(conversations).where(conversations.c.tenant_id == made["tenant"]))
        await s.execute(delete(memberships).where(memberships.c.tenant_id == made["tenant"]))
    async with db.identity_session() as s:
        await s.execute(delete(login_tokens).where(login_tokens.c.user_id == made["user"]))
        await s.execute(delete(users).where(users.c.id == made["user"]))


@pytest.fixture
async def shop(db: Database):
    made = await _make_shop(db)
    yield made
    await _drop_shop(db, made)


@pytest.fixture
async def other_shop(db: Database):
    """A second, fully populated merchant. §6.4 requires two, not one."""
    made = await _make_shop(db)
    yield made
    await _drop_shop(db, made)


def cookie_for(user_id: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user_id, get_settings().secret_key)}


def queue_of(client: TestClient, shop: dict[str, str], *, query: str = "") -> list[dict]:
    response = client.get(
        f"/v1/console/shops/{shop['tenant']}/review{query}", cookies=cookie_for(shop["user"])
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class TestOnlyYourOwnShop:
    """`console.md §6.1`, §6.2 and §6.4 — the deterministic bar."""

    def test_a_person_reaches_the_shop_they_hold_a_membership_for(
        self, client: TestClient, shop
    ) -> None:
        assert len(queue_of(client, shop)) == 2

    def test_another_persons_shop_is_not_reachable(
        self, client: TestClient, shop, other_shop
    ) -> None:
        """§6.4, with two tenants populated. Both have rows; neither may see the
        other's."""
        response = client.get(
            f"/v1/console/shops/{other_shop['tenant']}/review", cookies=cookie_for(shop["user"])
        )
        assert response.status_code == 404
        assert other_shop["answered"] not in response.text

    def test_a_tenant_this_person_cannot_act_for_is_404_and_not_403(
        self, client: TestClient, shop, other_shop
    ) -> None:
        """The two answers are collapsed on purpose. A 403 would confirm that a
        tenant id exists, turning this route into a way of asking whether a
        given merchant is a customer."""
        real = client.get(
            f"/v1/console/shops/{other_shop['tenant']}/review", cookies=cookie_for(shop["user"])
        )
        invented = client.get(
            "/v1/console/shops/tn_does_not_exist/review", cookies=cookie_for(shop["user"])
        )
        assert real.status_code == invented.status_code == 404
        assert real.json()["error"]["message"] == invented.json()["error"]["message"]

    def test_the_tenant_in_the_url_is_a_suggestion_and_not_authorisation(
        self, client: TestClient, shop, other_shop
    ) -> None:
        """`AGENTS.md` rule 3. Grading is a write, so this is the one that would
        hurt: a URL the browser edits must not become permission to change
        somebody else's row."""
        response = client.post(
            f"/v1/console/shops/{other_shop['tenant']}/review/{other_shop['answered']}/grade",
            json={"verdict": "agree"},
            cookies=cookie_for(shop["user"]),
        )
        assert response.status_code == 404

    def test_no_session_reaches_nothing(self, client: TestClient, shop) -> None:
        assert client.get(f"/v1/console/shops/{shop['tenant']}/review").status_code == 401

    def test_a_forged_cookie_reaches_nothing(self, client: TestClient, shop) -> None:
        forged = issue(shop["user"], "not-the-servers-secret")
        response = client.get(
            f"/v1/console/shops/{shop['tenant']}/review", cookies={COOKIE_NAME: forged}
        )
        assert response.status_code == 401

    async def test_a_revoked_membership_reaches_nothing_immediately(
        self, client: TestClient, db: Database, shop
    ) -> None:
        """§6.2. Not at cookie expiry — on the very next request. This is the
        reason the cookie carries a person and nothing else."""
        assert queue_of(client, shop)

        async with db.tenant_session(shop["tenant"]) as s:
            await s.execute(
                memberships.update()
                .where(memberships.c.id == shop["membership"])
                .values(revoked_at=datetime.now(UTC))
            )

        after = client.get(
            f"/v1/console/shops/{shop['tenant']}/review", cookies=cookie_for(shop["user"])
        )
        assert after.status_code == 404


class TestTheEvidenceIsThere:
    """`console.md §3.2` — the rule this screen exists for."""

    def test_the_shoppers_question_travels_with_the_draft(self, client: TestClient, shop) -> None:
        """It lives in `conversation_messages`, not in the shadow row. A queue
        that forgot to join it looks complete and is ungradeable."""
        answered = next(t for t in queue_of(client, shop) if t["id"] == shop["answered"])
        assert answered["question"]["text"] == "can I return these after 20 days?"
        assert answered["question"]["recorded"] is True

    def test_a_cited_policy_arrives_as_the_merchants_own_words(
        self, client: TestClient, shop
    ) -> None:
        answered = next(t for t in queue_of(client, shop) if t["id"] == shop["answered"])
        document = next(e for e in answered["evidence"] if e["kind"] == "document")
        assert document["available"] is True
        assert "within 30 days" in document["excerpt"]

    def test_a_tool_is_named_and_says_where_its_result_went(self, client: TestClient, shop) -> None:
        answered = next(t for t in queue_of(client, shop) if t["id"] == shop["answered"])
        tool = next(e for e in answered["evidence"] if e["kind"] == "tool")
        assert tool["id"] == "get_order"
        assert tool["available"] is False
        assert "audit log" in tool["reason"]


class TestAWithheldTurnIsInTheQueueAndLooksIt:
    """ADR-0020, on the merchant's side of the product."""

    def test_the_declined_turn_is_in_the_queue(self, client: TestClient, shop) -> None:
        """The one a queue built around "show the answers" would drop. It is the
        interesting one."""
        assert shop["declined"] in {turn["id"] for turn in queue_of(client, shop)}

    def test_the_declined_turn_explains_itself_rather_than_rendering_empty(
        self, client: TestClient, shop
    ) -> None:
        declined = next(t for t in queue_of(client, shop) if t["id"] == shop["declined"])
        assert declined["draft"] == ""
        assert declined["no_draft_reason"], "an empty draft with no words is ADR-0020's silence"
        assert declined["escalated"] is True

    def test_every_row_says_it_was_withheld(self, client: TestClient, shop) -> None:
        assert all(turn["withheld"] is True for turn in queue_of(client, shop))

    def test_the_filter_is_on_the_human_and_never_on_what_the_agent_did(
        self, client: TestClient, shop
    ) -> None:
        """`graded=false` is the reviewer's working set. There is no filter that
        hides declines, and adding one is what this asserts against."""
        ungraded = queue_of(client, shop, query="?graded=false")
        assert {turn["id"] for turn in ungraded} == {shop["answered"], shop["declined"]}


class TestGrading:
    def test_a_verdict_is_recorded_against_the_authenticated_person(
        self, client: TestClient, shop
    ) -> None:
        """Not a name the browser supplied. The first grade in this system that
        can answer "who approved this?" with something that cannot be typed in."""
        response = client.post(
            f"/v1/console/shops/{shop['tenant']}/review/{shop['answered']}/grade",
            json={"verdict": "agree", "note": "matches our policy page"},
            cookies=cookie_for(shop["user"]),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["verdict"] == "agree"
        assert data["reviewed_by"] == shop["user"]
        assert data["note"] == "matches our policy page"

    def test_the_browser_cannot_sign_somebody_elses_opinion(self, client: TestClient, shop) -> None:
        """`extra="forbid"` on the model. If `reviewed_by` were accepted here,
        one reviewer could attribute a verdict to another."""
        response = client.post(
            f"/v1/console/shops/{shop['tenant']}/review/{shop['answered']}/grade",
            json={"verdict": "agree", "reviewed_by": "usr_somebody_else"},
            cookies=cookie_for(shop["user"]),
        )
        assert response.status_code == 400

    def test_a_grade_may_be_changed(self, client: TestClient, shop) -> None:
        """Deliberate. Telling a reviewer their mis-click is permanent is the
        pressure that produces careless grades."""
        for verdict in ("agree", "would_have_harmed"):
            response = client.post(
                f"/v1/console/shops/{shop['tenant']}/review/{shop['answered']}/grade",
                json={"verdict": verdict},
                cookies=cookie_for(shop["user"]),
            )
            assert response.status_code == 200
        assert response.json()["data"]["verdict"] == "would_have_harmed"

    def test_an_unknown_turn_is_404(self, client: TestClient, shop) -> None:
        response = client.post(
            f"/v1/console/shops/{shop['tenant']}/review/msg_nope/grade",
            json={"verdict": "agree"},
            cookies=cookie_for(shop["user"]),
        )
        assert response.status_code == 404

    def test_grading_moves_a_turn_between_the_two_working_sets(
        self, client: TestClient, shop
    ) -> None:
        client.post(
            f"/v1/console/shops/{shop['tenant']}/review/{shop['answered']}/grade",
            json={"verdict": "disagree"},
            cookies=cookie_for(shop["user"]),
        )
        assert {t["id"] for t in queue_of(client, shop, query="?graded=true")} == {shop["answered"]}
        assert {t["id"] for t in queue_of(client, shop, query="?graded=false")} == {
            shop["declined"]
        }


class TestTheScorecardCountsOnlyThisShop:
    def test_counts_are_this_tenants_alone(self, client: TestClient, shop, other_shop) -> None:
        response = client.get(
            f"/v1/console/shops/{shop['tenant']}/review/scorecard", cookies=cookie_for(shop["user"])
        )
        assert response.status_code == 200
        card = response.json()["data"]
        assert card["recorded"] == 2, "the other shop's two turns must not be counted here"

    def test_an_ungraded_queue_reports_no_rate(self, client: TestClient, shop) -> None:
        card = client.get(
            f"/v1/console/shops/{shop['tenant']}/review/scorecard", cookies=cookie_for(shop["user"])
        ).json()["data"]
        assert card["agreement_rate"] is None
        assert card["harm_free"] is None

    def test_a_zero_cost_is_flagged_as_unmeasured(self, client: TestClient, shop) -> None:
        """`CLAUDE.md §4`. A local model costs zero and an unpriced cloud model
        records zero; the screen must not print "$0.00" for either."""
        card = client.get(
            f"/v1/console/shops/{shop['tenant']}/review/scorecard", cookies=cookie_for(shop["user"])
        ).json()["data"]
        assert card["cost"]["measured"] is False


class TestNoAuthorityAndNoOtherTenantInAnyBody:
    """`console.md §6.4` and §6.6, asserted across every endpoint on this screen."""

    def test_no_response_contains_an_api_key_or_another_tenants_id(
        self, client: TestClient, shop, other_shop
    ) -> None:
        tenant = shop["tenant"]
        bodies = [
            client.get(f"/v1/console/shops/{tenant}/review", cookies=cookie_for(shop["user"])).text,
            client.get(
                f"/v1/console/shops/{tenant}/review/scorecard", cookies=cookie_for(shop["user"])
            ).text,
            client.post(
                f"/v1/console/shops/{tenant}/review/{shop['answered']}/grade",
                json={"verdict": "agree"},
                cookies=cookie_for(shop["user"]),
            ).text,
        ]
        for body in bodies:
            assert "fn_sk_" not in body
            assert "fn_pk_" not in body
            assert other_shop["tenant"] not in body
            assert other_shop["user"] not in body
