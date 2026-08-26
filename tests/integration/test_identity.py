"""Signing a human in, against a real database. ADR-0026.

The half of identity that cannot be tested without PostgreSQL, and the half
where being wrong costs the most: **Row-Level Security is enforced by the
database, so a policy no test exercises is a policy nobody has.**

The check that matters most here is the last one — two people, two merchants,
and neither able to see the other's. It is written with two tenants populated
rather than one, because a single-tenant test passes identically whether
isolation works or does not exist at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text

from neura_core import Database, ids, load_env
from neura_core.identity import login as login_service
from neura_core.identity import may_act_for, memberships_for, redeem, request_sign_in_link
from neura_core.identity.schema import login_tokens, memberships, users

pytestmark = pytest.mark.integration

CONSOLE = "http://localhost:3000"


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    await database.dispose()


@pytest.fixture
async def people(db: Database):
    """Two people, two merchants, one membership each.

    Torn down by id rather than by truncating: a test that empties tables it did
    not create will one day be run against something that mattered.
    """
    made = {
        "alice": ids.new_id(ids.USER),
        "bob": ids.new_id(ids.USER),
        "tn_a": ids.new_id(ids.TENANT),
        "tn_b": ids.new_id(ids.TENANT),
        "mem_a": ids.new_id(ids.MEMBERSHIP),
        "mem_b": ids.new_id(ids.MEMBERSHIP),
    }
    async with db.identity_session() as s:
        await s.execute(
            users.insert().values(
                [
                    {
                        "id": made["alice"],
                        "email": f"{made['alice']}@example.com",
                        "name": "Alice",
                    },
                    {"id": made["bob"], "email": f"{made['bob']}@example.com", "name": "Bob"},
                ]
            )
        )
    # Memberships are tenant-scoped and forced, so each insert needs its own
    # tenant-scoped transaction — which is itself a small proof the policy works.
    for who, tenant, mem in (("alice", "tn_a", "mem_a"), ("bob", "tn_b", "mem_b")):
        async with db.tenant_session(made[tenant]) as s:
            await s.execute(
                memberships.insert().values(
                    id=made[mem], tenant_id=made[tenant], user_id=made[who], role="owner"
                )
            )

    yield made

    for tenant, mem in (("tn_a", "mem_a"), ("tn_b", "mem_b")):
        async with db.tenant_session(made[tenant]) as s:
            await s.execute(delete(memberships).where(memberships.c.id == made[mem]))
    async with db.identity_session() as s:
        await s.execute(
            delete(login_tokens).where(login_tokens.c.user_id.in_([made["alice"], made["bob"]]))
        )
        await s.execute(delete(users).where(users.c.id.in_([made["alice"], made["bob"]])))


class TestSignIn:
    async def test_a_link_is_minted_for_a_known_address(self, db: Database, people) -> None:
        async with db.identity_session() as s:
            request = await request_sign_in_link(
                s, email=f"{people['alice']}@example.com", console_base_url=CONSOLE
            )
        assert request.minted
        assert request.user_id == people["alice"]
        assert request.url.startswith(f"{CONSOLE}/auth/verify?token=")

    async def test_an_unknown_address_mints_nothing_and_says_nothing(self, db: Database) -> None:
        """The anti-enumeration rule. Same return value, so the caller cannot leak."""
        async with db.identity_session() as s:
            request = await request_sign_in_link(
                s, email="nobody@example.com", console_base_url=CONSOLE
            )
        assert not request.minted
        assert request.user_id == ""

    async def test_email_matching_is_case_insensitive(self, db: Database, people) -> None:
        """CITEXT. Otherwise Owner@shop and owner@shop are two accounts, and the
        second one silently has no access to the first one's shop."""
        async with db.identity_session() as s:
            request = await request_sign_in_link(
                s, email=f"{people['alice']}@example.com".upper(), console_base_url=CONSOLE
            )
        assert request.user_id == people["alice"]

    async def test_the_plaintext_token_is_never_stored(self, db: Database, people) -> None:
        async with db.identity_session() as s:
            request = await request_sign_in_link(
                s, email=f"{people['alice']}@example.com", console_base_url=CONSOLE
            )
        async with db.identity_session() as s:
            stored = (
                (
                    await s.execute(
                        select(login_tokens.c.token_hash).where(
                            login_tokens.c.user_id == people["alice"]
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert stored
        assert request.token not in stored, "the token itself reached a column"

    async def test_a_token_redeems_once_and_only_once(self, db: Database, people) -> None:
        """The forwarded-link case. Two redemptions, exactly one winner."""
        async with db.identity_session() as s:
            request = await request_sign_in_link(
                s, email=f"{people['alice']}@example.com", console_base_url=CONSOLE
            )

        async with db.identity_session() as s:
            first = await redeem(s, token=request.token)
        async with db.identity_session() as s:
            second = await redeem(s, token=request.token)

        assert first == people["alice"]
        assert second == "", "a consumed link signed somebody in a second time"

    async def test_an_expired_token_is_refused(self, db: Database, people) -> None:
        async with db.identity_session() as s:
            request = await request_sign_in_link(
                s, email=f"{people['alice']}@example.com", console_base_url=CONSOLE
            )
        later = datetime.now(UTC) + login_service.TOKEN_TTL + timedelta(minutes=1)

        async with db.identity_session() as s:
            assert await redeem(s, token=request.token, now=later) == ""

    async def test_an_invented_token_is_refused(self, db: Database) -> None:
        async with db.identity_session() as s:
            assert await redeem(s, token="not-a-real-token") == ""
            assert await redeem(s, token="") == ""


class TestMemberships:
    async def test_a_person_sees_their_own_membership(self, db: Database, people) -> None:
        async with db.identity_session(people["alice"]) as s:
            held = await memberships_for(s, people["alice"])
        assert [m.tenant_id for m in held] == [people["tn_a"]]

    async def test_a_person_cannot_see_another_persons_membership(
        self, db: Database, people
    ) -> None:
        """The check this whole file exists for.

        Two tenants are populated, so a pass here means the policy filtered
        something rather than there being nothing to filter.
        """
        async with db.identity_session(people["alice"]) as s:
            held = await memberships_for(s, people["alice"])

        assert people["tn_b"] not in [m.tenant_id for m in held]

    async def test_may_act_for_refuses_a_tenant_the_person_does_not_hold(
        self, db: Database, people
    ) -> None:
        """A tenant id in a request is a suggestion until this says otherwise."""
        async with db.identity_session(people["alice"]) as s:
            assert await may_act_for(s, user_id=people["alice"], tenant_id=people["tn_a"])
            assert not await may_act_for(s, user_id=people["alice"], tenant_id=people["tn_b"])

    async def test_a_session_that_set_no_user_id_sees_nothing(self, db: Database, people) -> None:
        """The policy reads `app.user_id`. Forgetting it must fail closed."""
        async with db.identity_session() as s:
            held = await memberships_for(s, people["alice"])
        assert held == [], "memberships were readable without app.user_id being set"

    async def test_a_revoked_membership_grants_nothing(self, db: Database, people) -> None:
        """Revocation must bite immediately — the cookie cannot be recalled."""
        async with db.tenant_session(people["tn_a"]) as s:
            await s.execute(
                memberships.update()
                .where(memberships.c.id == people["mem_a"])
                .values(revoked_at=datetime.now(UTC))
            )

        async with db.identity_session(people["alice"]) as s:
            assert await memberships_for(s, people["alice"]) == []
            assert not await may_act_for(s, user_id=people["alice"], tenant_id=people["tn_a"])


class TestTheBootstrapSessionIsNarrow:
    async def test_it_cannot_read_tenant_scoped_rows(self, db: Database, people) -> None:
        """`identity_session` sets no `app.tenant_id`, so tenant tables are dark.

        If this ever passes rows back, the sign-in path has become a way to read
        merchant data without naming a merchant.
        """
        async with db.identity_session(people["alice"]) as s:
            rows = (await s.execute(text("SELECT count(*) FROM tenants"))).scalar()
        assert rows == 0, "the sign-in bootstrap could see tenant rows"
