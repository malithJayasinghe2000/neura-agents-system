"""ADR-0044 phase 1 — the parts that are properties of our code, not of PostgreSQL.

What a shop may send, who may send it, how long it lives, and that nothing is
shown. The database halves — isolation, the sweep, the key-issue refusal and the
route end to end — are in ``tests/integration/test_observation_postgres.py``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from neura_api.jobs.retention import RETENTION, RETENTION_SWEEP, SWEEP_INTERVAL, SweepResult
from neura_api.main import create_app
from neura_api.routes.observe import admit
from neura_core import ForbiddenError, Settings
from neura_core.observation import (
    CLOCK_SKEW,
    OBSERVE_WRITE,
    ObservedEvent,
    ObservedEventType,
    inadmissible,
)
from neura_core.tenancy import ApiKeyKind, AuthenticatedCaller
from neura_core.tenancy.models import ApiKey, Tenant

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
WEEK = timedelta(days=7)


def _event(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "event_id": "01J8ZQ7Y3W5K2M9N4P6R8T0V1X",
        "session_id": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "type": "product.viewed",
        "product_id": "1315",
        "occurred_at": NOW.isoformat(),
        "in_stock": False,
    }
    body.update(overrides)
    return body


def _caller(*, kind: ApiKeyKind = ApiKeyKind.SECRET, dpa: datetime | None = NOW) -> Any:
    tenant = Tenant(tenant_id="tn_obs", name="Shop", dpa_signed_at=dpa)
    key = ApiKey(
        id="key_obs",
        tenant_id="tn_obs",
        kind=kind,
        token_prefix="fn_sk_test_x",
        scopes=frozenset({OBSERVE_WRITE}),
    )
    return AuthenticatedCaller(tenant=tenant, api_key=key)


class TestWhatAShopMaySend:
    """§4: a session id, an event type, a product, a timestamp. Nothing else."""

    def test_a_well_formed_event_is_accepted(self) -> None:
        event = ObservedEvent.model_validate(_event())
        assert event.type is ObservedEventType.PRODUCT_VIEWED

    @pytest.mark.parametrize("field", ["ip", "user_agent", "email", "customer_id", "url"])
    def test_anything_section_4_does_not_name_is_refused_not_dropped(self, field: str) -> None:
        """Dropped would be *collected and discarded* — §3 says that is not a control.

        A refusal that names the field is how the shop's developer finds out.
        """
        with pytest.raises(ValidationError) as refused:
            ObservedEvent.model_validate(_event(**{field: "203.0.113.9"}))
        assert field in str(refused.value)

    @pytest.mark.parametrize(
        "session_id",
        [
            "jane@example.com",  # an address is not an opaque identifier
            "Jane Smith lives here",  # nor is a name
            "short",  # too short to be a keyed hash
            "a" * 129,
        ],
    )
    def test_a_session_id_must_be_an_opaque_token(self, session_id: str) -> None:
        with pytest.raises(ValidationError):
            ObservedEvent.model_validate(_event(session_id=session_id))

    @pytest.mark.parametrize(
        "product_id", ["TEA.400G", "gid://shop/Product/1", "SKU 12", "Th\u00e9-vert/250g", "1042"]
    )
    def test_a_product_id_is_any_id_the_bridge_format_allows(self, product_id: str) -> None:
        """G59: the format lets a product's `external_id` be any text, and the session
        id's opaque-token rule had been reused for it, so a shop whose ids carry a
        dot, a slash or a space got a 400 for every view and an empty Sold out list."""
        event = ObservedEvent.model_validate(_event(product_id=product_id))
        assert event.product_id == product_id

    @pytest.mark.parametrize("product_id", ["", "   ", "line\nbreak", "tab\there", "a" * 129])
    def test_a_product_id_still_has_to_be_an_id(self, product_id: str) -> None:
        with pytest.raises(ValidationError):
            ObservedEvent.model_validate(_event(product_id=product_id))

    def test_a_time_without_a_zone_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            ObservedEvent.model_validate(_event(occurred_at="2026-09-26T12:00:00"))

    def test_phase_1_records_exactly_two_things(self) -> None:
        """Owner decision, 2026-09-26. A third is a decision, not an enum member."""
        assert {t.value for t in ObservedEventType} == {"product.viewed", "cart.added"}

    def test_a_view_must_say_whether_it_could_be_bought(self) -> None:
        """ADR-0049: "sold out when viewed" cannot be worked out on Saturday."""
        body = _event()
        del body["in_stock"]
        with pytest.raises(ValidationError, match="in_stock"):
            ObservedEvent.model_validate(body)

    def test_a_basket_add_does_not_carry_it(self) -> None:
        """An add is in stock by definition; `in_stock: false` on one is a contradiction."""
        with pytest.raises(ValidationError, match="in_stock"):
            ObservedEvent.model_validate(_event(type="cart.added", in_stock=False))
        body = _event(type="cart.added")
        del body["in_stock"]
        assert ObservedEvent.model_validate(body).in_stock is None

    @pytest.mark.parametrize("kind", ["search.performed", "category.viewed", "page.viewed"])
    def test_anything_else_is_refused(self, kind: str) -> None:
        """Searches especially: recording one means keeping what someone typed."""
        with pytest.raises(ValidationError):
            ObservedEvent.model_validate(_event(type=kind))


class TestTheWindow:
    """The shop's clock may not decide how long we hold a row."""

    def test_now_is_admissible(self) -> None:
        assert inadmissible(ObservedEvent.model_validate(_event()), now=NOW, retention=WEEK) is None

    def test_a_little_clock_skew_is_tolerated(self) -> None:
        ahead = NOW + CLOCK_SKEW - timedelta(seconds=1)
        event = ObservedEvent.model_validate(_event(occurred_at=ahead.isoformat()))
        assert inadmissible(event, now=NOW, retention=WEEK) is None

    def test_the_future_is_refused(self) -> None:
        """Retention counts from `occurred_at`; next year's date would buy a year."""
        event = ObservedEvent.model_validate(
            _event(occurred_at=(NOW + timedelta(days=365)).isoformat())
        )
        assert inadmissible(event, now=NOW, retention=WEEK) == "occurred_at is in the future"

    def test_what_the_next_sweep_would_delete_is_never_stored(self) -> None:
        event = ObservedEvent.model_validate(
            _event(occurred_at=(NOW - timedelta(days=8)).isoformat())
        )
        assert "older than the retention period" in (
            inadmissible(event, now=NOW, retention=WEEK) or ""
        )


class TestWhoMaySend:
    """§2 and ADR-0042 §2, as code — the route calls this before it writes."""

    def test_a_secret_key_with_an_agreement_is_admitted(self) -> None:
        admit(_caller())

    def test_a_browser_key_is_refused_even_holding_the_scope(self) -> None:
        """No script of ours runs in a shopper's browser, and fn_pk_ is a browser's key."""
        with pytest.raises(ForbiddenError) as refused:
            admit(_caller(kind=ApiKeyKind.PUBLIC))
        assert refused.value.code == "OBSERVE_BROWSER_KEY"

    def test_no_agreement_means_nothing_is_stored(self) -> None:
        with pytest.raises(ForbiddenError) as refused:
            admit(_caller(dpa=None))
        assert refused.value.code == "DPA_REQUIRED"


class TestRetentionSettings:
    """ADR-0042 §3: a retention setting nobody enforces is a control that reads green."""

    def test_the_defaults(self) -> None:
        settings = Settings()
        assert settings.retention_conversations_days == 90
        # The longest window anything designed reads: ADR-0046's weekly count
        # and ADR-0044 §6's "third visit in a week".
        assert settings.retention_observed_events_days == 7
        # ADR-0062 §4 (R30): unanswered after 30 days, the typed email goes.
        assert settings.retention_handover_emails_days == 30

    def test_zero_days_is_refused_for_a_typed_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETENTION_HANDOVER_EMAILS_DAYS", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_zero_days_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Zero would delete every row on every pass — or, read another way, mean
        'never'. Neither is a retention period."""
        monkeypatch.setenv("RETENTION_OBSERVED_EVENTS_DAYS", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_every_retention_setting_is_either_enforced_or_named_as_not(self) -> None:
        """The guard against a *fifth* unread setting.

        Every ``RETENTION_*`` line in ``.env.example`` must be read by
        ``Settings`` (and therefore by the sweep), or be one of the two that
        ADR-0048 §5 names as not enforced, with the reason. Adding a sixth that
        nothing reads fails here.
        """
        example = (ROOT / ".env.example").read_text()
        declared = set(re.findall(r"^(RETENTION_[A-Z_]+)=", example, flags=re.MULTILINE))
        enforced = {
            field.alias
            for field in Settings.model_fields.values()
            if field.alias and field.alias.startswith("RETENTION_")
        }
        not_enforced = {"RETENTION_AUDIT_LOG_DAYS", "RETENTION_TRACES_DAYS"}

        assert enforced == {
            "RETENTION_CONVERSATIONS_DAYS",
            "RETENTION_OBSERVED_EVENTS_DAYS",
            # ADR-0062 §4: a handed-over shopper's typed email (R30).
            "RETENTION_HANDOVER_EMAILS_DAYS",
        }
        assert declared == enforced | not_enforced
        assert not (enforced & not_enforced)


class TestTheSweepJob:
    def test_one_kind_and_one_live_job_per_tenant(self) -> None:
        assert RETENTION_SWEEP == "retention.sweep"
        assert RETENTION == "retention"

    def test_it_runs_daily(self) -> None:
        """Retention is counted in days; daily holds a row at most a day past it."""
        assert timedelta(days=1) == SWEEP_INTERVAL

    def test_the_summary_says_when_it_stops(self) -> None:
        done = SweepResult(
            events_deleted=3,
            conversations_deleted=1,
            emails_deleted=2,
            no_agreement=False,
            remaining=False,
        )
        assert "not re-armed" in done.summary()
        assert "2 unanswered email(s) deleted" in done.summary()
        withdrawn = SweepResult(
            events_deleted=5,
            conversations_deleted=0,
            emails_deleted=0,
            no_agreement=True,
            remaining=True,
        )
        assert "no agreement" in withdrawn.summary()


class TestPhaseOneShowsNothing:
    """§9: collect and prove. Displaying is ADR-0046 stage 1."""

    @pytest.fixture
    def client(self) -> Any:
        with TestClient(create_app()) as test_client:
            yield test_client

    def test_the_only_observe_route_is_a_write(self, client: TestClient) -> None:
        paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]
        observe = {path: set(ops) for path, ops in paths.items() if path.startswith("/v1/observe")}
        assert observe == {"/v1/observe/events": {"post"}}

    def test_no_key_is_401(self, client: TestClient) -> None:
        response = client.post("/v1/observe/events", json=_event())
        assert response.status_code == 401
