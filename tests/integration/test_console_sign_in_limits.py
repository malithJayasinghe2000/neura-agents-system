"""G97: asking for a sign-in link is limited, per network address and per email.

Before this, ``POST /v1/console/auth/request-link`` had no limit at all, so
anyone could make NEURA send any number of sign-in emails to one address, from
NEURA's own email account. What these tests hold the fix to:

* one email gets only a few links an hour, from any number of addresses;
* one network address gets only a few links an hour, for any number of emails;
* the limit answers the same whether or not the email has an account, so it
  says nothing about who uses NEURA (console.md §4.3 rule 4);
* a refused request sends no email.

Needs Redis, as every rate limit does; skipped, not passed, without it. Each test
uses its own made-up address and email, so counters left from an earlier run in
the same hour cannot change the answer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.email import Mailer, SendResult
from neura_core.identity.schema import login_tokens, users

pytestmark = pytest.mark.integration

PER_EMAIL = 3
PER_CLIENT = 5


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("NEURA_TRUSTED_PROXY_HOPS", "1")
    monkeypatch.setenv("RATE_LIMIT_SIGN_IN_PER_EMAIL", str(PER_EMAIL))
    monkeypatch.setenv("RATE_LIMIT_SIGN_IN_PER_CLIENT", str(PER_CLIENT))
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            if not test_client.app.state.limiter.available:
                pytest.skip("no Redis: rate limits cannot be checked")
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
def mail(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    def send(self: Mailer, *, to: str, subject: str, body: str) -> SendResult:
        sent.append(to)
        return SendResult(sent=True)

    monkeypatch.setattr(Mailer, "send", send)
    return sent


def fresh_email() -> str:
    return f"limit-{ids.new_id(ids.USER).lower()}@example.com"


def fresh_address() -> str:
    return f"probe-{ids.new_id(ids.REQUEST).lower()}"


def ask(client: TestClient, email: str, address: str):
    return client.post(
        "/v1/console/auth/request-link",
        json={"email": email},
        headers={"X-Forwarded-For": address},
    )


class TestSignInIsLimited:
    def test_one_email_gets_only_a_few_links_an_hour(self, client: TestClient) -> None:
        email = fresh_email()
        answers = [ask(client, email, fresh_address()).status_code for _ in range(PER_EMAIL + 1)]
        assert answers == [200] * PER_EMAIL + [429]

    def test_one_address_gets_only_a_few_links_an_hour(self, client: TestClient) -> None:
        address = fresh_address()
        answers = [ask(client, fresh_email(), address).status_code for _ in range(PER_CLIENT + 1)]
        assert answers == [200] * PER_CLIENT + [429]

    def test_the_refusal_is_plain_and_has_its_code(self, client: TestClient) -> None:
        email = fresh_email()
        for _ in range(PER_EMAIL):
            ask(client, email, fresh_address())
        refused = ask(client, email, fresh_address())
        assert refused.status_code == 429
        error = refused.json()["error"]
        assert error["code"] == "RATE_LIMITED"
        assert error["message"] == (
            "Too many sign-in links were asked for. Please wait a while, then try again."
        )

    async def test_it_says_nothing_about_who_has_an_account(
        self, client: TestClient, db: Database, mail: list[str]
    ) -> None:
        known = fresh_email()
        user = ids.new_id(ids.USER)
        async with db.identity_session() as session:
            await session.execute(users.insert().values(id=user, email=known))
        try:
            known_answers = [ask(client, known, fresh_address()) for _ in range(PER_EMAIL + 1)]
            unknown = fresh_email()
            unknown_answers = [ask(client, unknown, fresh_address()) for _ in range(PER_EMAIL + 1)]
            assert [r.status_code for r in known_answers] == [
                r.status_code for r in unknown_answers
            ]
            assert known_answers[0].json()["data"] == unknown_answers[0].json()["data"]

            def refusal(response) -> dict:
                error = dict(response.json()["error"])
                error.pop("request_id", None)
                return error

            assert refusal(known_answers[-1]) == refusal(unknown_answers[-1])
            # The known address was mailed for each allowed request, and not for
            # the refused one.
            assert mail == [known] * PER_EMAIL
        finally:
            async with db.identity_session() as session:
                await session.execute(delete(login_tokens).where(login_tokens.c.user_id == user))
                await session.execute(delete(users).where(users.c.id == user))
