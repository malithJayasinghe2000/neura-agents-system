"""The API's serving layer — everything that does not need a database.

The most important test in this file is the first class. **The eval suite is only
evidence about what is served if the served runtime is the runtime the suite
measured**, and until 1.14 that was true by there being one caller. Now there are
two — the eval target and ``CareRunner`` — so it has to be asserted rather than
observed, for exactly the reason ``make eval-guard-off`` exists: a measurement
mode that differs from the real thing in more than one respect produces a 1.00
about something nobody ships.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from neura_agent_care.evals.store import ALL_CAPABILITIES
from neura_agent_care.evals.target import CareTarget
from neura_agent_care.runtime import MAX_TOOL_CALLS, build_runtime
from neura_agent_care.serving import CareRunner, _citations, _outcome, _state
from neura_agent_care.tools import TOOL_SCOPES
from neura_agent_core.conversations import ConversationState
from neura_agent_core.serving import (
    RUNNER_ENTRY_POINT_GROUP,
    Citation,
    Progress,
    ProgressKind,
    TurnOutcome,
)
from neura_agent_core.tools.executor import ToolInvocation
from neura_api.envelopes import decode_cursor, encode_cursor, envelope, page
from neura_api.metering import MeteredLLM
from neura_api.ratelimit import RateLimiter, Subject, enforce, subjects_for
from neura_api.turns import _delta
from neura_core import RateLimitError, ValidationError, get_settings
from neura_core.tenancy import (
    Admission,
    ApiKey,
    ApiKeyKind,
    AuthenticatedCaller,
    Tenant,
    TenantConfig,
    resolve_runtime_policy,
)
from neura_core.webhooks import DeliveryStatus, WebhookEvent, backoff_for, sign
from neura_core.webhooks.repository import MAX_ATTEMPTS
from neura_core.webhooks.signing import matches, within_tolerance

TENANT = "tn_serving_test"


# ── Served equals measured ───────────────────────────────────────────────────


class TestTheServedRuntimeIsTheMeasuredRuntime:
    """Rule 4's premise, asserted rather than assumed.

    ``make eval`` measures a runtime built by ``evals/target.py``. A shopper
    talks to one built by ``serving.py``. If those two differ, the golden numbers
    are evidence about a system nobody uses — which is precisely the bug 1.12
    found in ``make eval-guard-off``, where a measurement mode differed from the
    real thing in a second, unnoticed respect and reported 1.00 for it.
    """

    def test_an_unconfigured_tenant_gets_the_evaluated_ceilings(self) -> None:
        tenant = Tenant(tenant_id=TENANT, name="Merchant", enabled_agents=frozenset({"care"}))
        policy = resolve_runtime_policy(tenant, "care", Decimal("0"))

        assert policy.admission is Admission.NORMAL
        assert policy.runtime_kwargs() == {
            "allowed_tools": None,
            "max_tool_calls": MAX_TOOL_CALLS,
        }

    def test_both_callers_equip_a_turn_identically(self) -> None:
        """Same tools, same ceiling, same guard state, same prompts.

        Compared field by field rather than by ``==``: a ``Runtime`` holds an
        adapter and an LLM client, which are different objects by construction
        and say nothing about whether the *agent* is configured the same way.
        """
        served = build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_1",
            adapter=object(),
            llm=object(),
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
            # What `TurnService` passes for an unconfigured tenant.
            allowed_tools=None,
            max_tool_calls=MAX_TOOL_CALLS,
        )
        evaluated = build_runtime(
            tenant_id=TENANT,
            conversation_id="cnv_1",
            adapter=object(),
            llm=object(),
            capabilities=ALL_CAPABILITIES,
            scopes=TOOL_SCOPES,
        )

        assert served.budget.max_tool_calls == evaluated.budget.max_tool_calls
        assert served.ctx.allowed_tools == evaluated.ctx.allowed_tools
        assert served.ctx.scopes == evaluated.ctx.scopes
        assert served.guard_enabled == evaluated.guard_enabled
        assert served.prompts == evaluated.prompts
        assert sorted(s.name for s in served.registry) == sorted(s.name for s in evaluated.registry)

    def test_a_hard_budget_empties_the_allowlist(self) -> None:
        """ADR-0015's escalate-only rung, reached through the serving path.

        No new branch in the graph: every proposed call is rejected by check 4
        of the policy engine and CARE hands over exactly as it already does when
        it cannot act.
        """
        tenant = Tenant(
            tenant_id=TENANT,
            name="Merchant",
            enabled_agents=frozenset({"care"}),
            config=TenantConfig(daily_cost_usd_soft=Decimal("1"), daily_cost_usd_hard=Decimal("2")),
        )
        policy = resolve_runtime_policy(tenant, "care", Decimal("5"))

        assert policy.admission is Admission.ESCALATE_ONLY
        assert policy.runtime_kwargs() == {"allowed_tools": frozenset(), "max_tool_calls": 0}


class TestTheRunnerIsDiscovered:
    def test_care_registers_a_runner_entry_point(self) -> None:
        """Discovered, never imported by name — the third seam of that shape."""
        from importlib.metadata import entry_points

        names = {ep.name for ep in entry_points(group=RUNNER_ENTRY_POINT_GROUP)}
        assert "care" in names

    def test_the_runner_key_matches_the_manifest(self) -> None:
        """A disagreement would bill one agent for another's work."""
        from neura_agent_care import MANIFEST

        assert CareRunner().key == MANIFEST.key


# ── Mapping a final state onto the wire ──────────────────────────────────────


class TestOutcomeMapping:
    def test_blocked_wins_over_escalated(self) -> None:
        assert _state(blocked=True, escalated=True) is ConversationState.BLOCKED

    def test_an_ordinary_answer_is_resolved(self) -> None:
        assert _state(blocked=False, escalated=False) is ConversationState.RESOLVED

    def test_a_declined_turn_is_still_an_answer(self) -> None:
        """A5's outcome: out of scope, no person needed, nobody's afternoon spent.

        It must not read as an escalation on the wire, or a merchant's
        escalation count would include every "what's the weather?".
        """
        outcome = _outcome({"reply": "I can't help with that.", "refused": True})
        assert outcome.state is ConversationState.RESOLVED
        assert outcome.refused is True
        assert outcome.escalated is False

    def test_tool_calls_count_only_successful_invocations(self) -> None:
        """A refused call never ran, so billing for it would be billing for a
        refusal — and inflating a merchant's tool-call count with the calls the
        policy engine stopped is the wrong way round."""
        outcome = _outcome(
            {
                "invocations": [
                    ToolInvocation(tool_name="get_order_status", ok=True, value="x"),
                    ToolInvocation(tool_name="search_products", ok=False, error="refused"),
                ]
            }
        )
        assert outcome.tool_calls == 1

    def test_citations_name_documents_by_type_and_id_and_tools_by_name(self) -> None:
        citations = _citations(
            {
                "sources": ["policy:returns#0", "policy:returns#1", "product:42#0"],
                "invocations": [ToolInvocation(tool_name="search_policies", ok=True, value="x")],
            }
        )
        assert citations == [
            Citation(type="policy", id="returns"),
            Citation(type="product", id="42"),
            Citation(type="tool", id="search_policies"),
        ]

    def test_the_products_the_answer_names_are_cited(self) -> None:
        """G114: GROW files a gap under the product a reply looked at, read from
        its ``product:`` citations, as SELL writes them. CARE named only the tool,
        so every CARE gap landed under *About your shop*. Only the products the
        answer names, and only from a catalogue lookup."""
        search = (
            "5: Green Tea Loose Leaf 100g — 1200.00 LKR, in stock\n"
            "4: Ceylon Black Tea BOPF 400g — 1500.00 LKR, in stock"
        )
        details = "Product 5: Green Tea Loose Leaf 100g\n  availability: in stock"
        reply = (
            "We have the Green Tea Loose Leaf 100g in stock for 1200.00 LKR, but our "
            "details do not state whether it is organic."
        )
        for value, tool in ((search, "search_products"), (details, "get_product_details")):
            citations = _citations(
                {
                    "reply": reply,
                    "invocations": [ToolInvocation(tool_name=tool, ok=True, value=value)],
                }
            )
            assert citations == [
                Citation(type="tool", id=tool),
                Citation(type="product", id="5"),
            ], tool

    def test_a_lookup_that_may_hold_a_customers_record_cites_no_product(self) -> None:
        citations = _citations(
            {
                "reply": "Your order has the Green Tea Loose Leaf 100g in it.",
                "invocations": [
                    ToolInvocation(
                        tool_name="get_order",
                        ok=True,
                        value="Product 5: Green Tea Loose Leaf 100g",
                        pii_output=True,
                    )
                ],
            }
        )
        assert citations == [Citation(type="tool", id="get_order")]

    def test_a_failed_tool_is_not_cited(self) -> None:
        """Citations are evidence the reply was checked against. A call that
        failed produced none."""
        citations = _citations(
            {"invocations": [ToolInvocation(tool_name="check_stock", ok=False, error="boom")]}
        )
        assert citations == []


class TestProgressCarriesNamesAndNothingElse:
    """A progress channel is the easiest place in a system to leak something.

    It is the one stream nobody treats as a response body, and "just for
    debugging" is how a tool's arguments reach a browser's console.
    """

    async def test_a_node_update_becomes_a_step_and_its_tools(self) -> None:
        from neura_agent_care.serving import _report

        seen: list[Progress] = []

        async def sink(progress: Progress) -> None:
            seen.append(progress)

        await _report(
            {
                "act": {
                    "invocations": [
                        ToolInvocation(
                            tool_name="get_order_status", ok=True, value="jane@example.com"
                        )
                    ]
                }
            },
            sink,
            set(),
        )

        assert seen == [
            Progress(kind=ProgressKind.STEP, name="act"),
            Progress(kind=ProgressKind.TOOL_CALL, name="get_order_status"),
        ]
        # The tool's *result* was a value that looks like personal data. Nothing
        # in the frames carries it.
        assert not any("example.com" in p.name for p in seen)

    async def test_a_tool_is_reported_once(self) -> None:
        from neura_agent_care.serving import _report

        seen: list[Progress] = []

        async def sink(progress: Progress) -> None:
            seen.append(progress)

        already = {"search_products"}
        await _report(
            {"act": {"invocations": [ToolInvocation(tool_name="search_products", ok=True)]}},
            sink,
            already,
        )
        assert [p.kind for p in seen] == [ProgressKind.STEP]


# ── Metering (open question P5, the client half) ─────────────────────────────


@dataclass
class _Usage:
    prompt_tokens: int = 11
    completion_tokens: int = 7


class _Response:
    def __init__(self) -> None:
        self.usage = _Usage()
        self.cost_usd = Decimal("0.000125")


class _StructuredResult:
    def __init__(self, attempts: int = 1) -> None:
        self.response = _Response()
        self.attempts = attempts


class _InnerLLM:
    role_map_name = "stub"
    embedding_model = "stub-embed"
    is_fully_local = True

    def __init__(self) -> None:
        self.last: Any = None
        self.response = _Response()

    async def chat(self, role: Any, request: Any) -> Any:
        self.last = (role, request)
        return self.response

    async def chat_structured(self, role: Any, request: Any, schema: Any) -> Any:
        return _StructuredResult(attempts=2)

    async def embed(self, texts: list[str]) -> Any:
        return self.response


class TestMeteringChangesNothing:
    async def test_the_providers_own_object_is_returned_unmodified(self) -> None:
        """Identity, not equality.

        "It just passes through" is exactly the kind of claim that stops being
        true during a refactor, and the failure would be invisible: a wrapper
        that rebuilt the response would still produce a plausible reply.
        """
        inner = _InnerLLM()
        metered = MeteredLLM(inner)

        response = await metered.chat("reasoner", "request")

        assert response is inner.response
        assert inner.last == ("reasoner", "request")

    async def test_every_call_is_counted(self) -> None:
        metered = MeteredLLM(_InnerLLM())

        await metered.chat("router", "r")
        await metered.embed(["query"])

        assert metered.spend.calls == 2
        assert metered.spend.prompt_tokens == 22
        assert metered.spend.completion_tokens == 14
        assert metered.spend.cost_usd == Decimal("0.00025")

    async def test_a_repaired_structured_call_counts_its_attempts(self) -> None:
        """`generate_structured` folds the repair's tokens into one response.
        Counting one call would under-report the model calls a merchant paid
        for."""
        metered = MeteredLLM(_InnerLLM())
        await metered.chat_structured("router", "r", object)
        assert metered.spend.calls == 2

    async def test_a_stubbed_client_without_usage_does_not_raise(self) -> None:
        """A meter that raised on a test double would make itself a reason tests
        fail rather than a thing they check."""

        class _Bare:
            async def chat(self, role: Any, request: Any) -> Any:
                return object()

        metered = MeteredLLM(_Bare())
        await metered.chat("router", "r")
        assert metered.spend.calls == 1
        assert metered.spend.cost_usd == Decimal("0")


class TestTheUsageDeltaSplitsItsSources:
    """P5: turns, LLM calls and cost from the client; tool calls and escalations
    from the graph. Neither side invents the other's numbers."""

    def test_a_resolved_turn(self) -> None:
        metered = MeteredLLM(_InnerLLM())
        metered.spend.calls = 4
        metered.spend.prompt_tokens = 900
        metered.spend.completion_tokens = 120
        metered.spend.cost_usd = Decimal("0.004")

        delta = _delta(
            TurnOutcome(reply="ok", state=ConversationState.RESOLVED, tool_calls=2),
            metered,
            conversation_started=True,
        )

        assert delta.conversations == 1
        assert delta.turns == 1
        assert delta.llm_calls == 4
        assert delta.tool_calls == 2
        assert delta.escalations == 0
        assert delta.cost_usd == Decimal("0.004")

    def test_a_blocked_turn_is_counted_and_costs_nothing(self) -> None:
        """A block ends the turn before any model call (ADR-0012's whole point).
        It is still a turn: the merchant used the service."""
        delta = _delta(
            TurnOutcome(reply="", state=ConversationState.BLOCKED, blocked=True),
            MeteredLLM(_InnerLLM()),
            conversation_started=True,
        )
        assert delta.turns == 1
        assert delta.blocked == 1
        assert delta.llm_calls == 0
        assert delta.cost_usd == Decimal("0")

    def test_a_second_turn_does_not_count_a_second_conversation(self) -> None:
        delta = _delta(
            TurnOutcome(reply="ok", state=ConversationState.RESOLVED),
            MeteredLLM(_InnerLLM()),
            conversation_started=False,
        )
        assert delta.conversations == 0
        assert delta.turns == 1


# ── Rate limiting (ADR-0017) ─────────────────────────────────────────────────


def _caller(kind: ApiKeyKind) -> AuthenticatedCaller:
    return AuthenticatedCaller(
        tenant=Tenant(tenant_id=TENANT, name="M", enabled_agents=frozenset({"care"})),
        api_key=ApiKey(
            id="key_1",
            tenant_id=TENANT,
            kind=kind,
            token_prefix="fn_pk_test_abc",
            scopes=frozenset({"care:chat:write"}),
            allowed_origins=("https://shop.example",),
        ),
    )


class TestRateLimitSubjects:
    def test_a_secret_key_is_limited_by_tenant_and_key(self) -> None:
        """The caller *is* the merchant's server. Narrowing further would
        throttle a legitimate batch integration for no security gain."""
        subjects = subjects_for(
            _caller(ApiKeyKind.SECRET), client="203.0.113.9", conversation_id="cnv_1"
        )
        assert [s.kind for s in subjects] == ["tenant", "key"]

    def test_a_public_key_adds_the_two_narrower_subjects(self) -> None:
        """This is the whole of P1: per-key is the shop, not the shopper."""
        subjects = subjects_for(
            _caller(ApiKeyKind.PUBLIC), client="203.0.113.9", conversation_id="cnv_1"
        )
        assert [s.kind for s in subjects] == ["tenant", "key", "client", "conversation"]

    def test_the_client_address_is_never_stored_in_the_counter_key(self) -> None:
        """An IP is personal data. What reaches Redis is a keyed hash inside a
        key that expires with its window."""
        subjects = subjects_for(
            _caller(ApiKeyKind.PUBLIC), client="203.0.113.9", conversation_id=None
        )
        client = next(s for s in subjects if s.kind == "client")
        bucket = client.bucket(window_s=60, now=0.0)

        assert "203.0.113.9" not in client.identity
        assert "203.0.113.9" not in bucket

    def test_two_addresses_produce_two_subjects(self) -> None:
        one = subjects_for(_caller(ApiKeyKind.PUBLIC), client="a", conversation_id=None)
        two = subjects_for(_caller(ApiKeyKind.PUBLIC), client="b", conversation_id=None)
        assert one[2].identity != two[2].identity


class _FakeRedis:
    """Enough Redis to count. Not a substitute for the integration test."""

    def __init__(self, *, broken: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: list[tuple[str, int]] = []
        self._broken = broken

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self, broken=self._broken)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis, *, broken: bool) -> None:
        self._redis = redis
        self._ops: list[tuple[str, Any]] = []
        self._broken = broken

    def incr(self, key: str) -> None:
        self._ops.append(("incr", key))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(("expire", (key, ttl)))

    async def execute(self) -> list[Any]:
        if self._broken:
            raise ConnectionError("redis is down")
        results: list[Any] = []
        for op, arg in self._ops:
            if op == "incr":
                self._redis.counts[arg] = self._redis.counts.get(arg, 0) + 1
                results.append(self._redis.counts[arg])
            else:
                self._redis.expiries.append(arg)
                results.append(True)
        return results


class TestRateLimiter:
    async def test_the_tightest_subject_is_reported(self) -> None:
        """A client backing off on the headers must back off on the constraint
        that will actually stop it."""
        limiter = RateLimiter(_FakeRedis(), window_s=60)
        verdict = await limiter.check(
            [Subject("tenant", "t", 600), Subject("conversation", "c", 20)], now=0.0
        )
        assert verdict.subject == "conversation"
        assert verdict.limit == 20
        assert verdict.remaining == 19

    async def test_every_subject_is_incremented_even_after_a_refusal(self) -> None:
        """Stopping at the first failure would leave the other counters
        under-counting exactly when a caller is at their limit."""
        redis = _FakeRedis()
        limiter = RateLimiter(redis, window_s=60)
        subjects = [Subject("tenant", "t", 0), Subject("key", "k", 100)]

        verdict = await limiter.check(subjects, now=0.0)

        assert verdict.allowed is False
        assert len(redis.counts) == 2

    async def test_the_expiry_is_set_on_every_request(self) -> None:
        """An EXPIRE skipped because the key "already existed" is how a counter
        becomes immortal — and an immortal counter locks a subject out
        permanently."""
        redis = _FakeRedis()
        limiter = RateLimiter(redis, window_s=60)
        await limiter.check([Subject("tenant", "t", 10)], now=0.0)
        await limiter.check([Subject("tenant", "t", 10)], now=1.0)
        assert len(redis.expiries) == 2

    async def test_a_refusal_carries_a_retry_after(self) -> None:
        limiter = RateLimiter(_FakeRedis(), window_s=60)
        verdict = await limiter.check([Subject("tenant", "t", 0)])
        assert not verdict.allowed
        assert "Retry-After" in verdict.headers()

        with pytest.raises(RateLimitError) as raised:
            enforce(verdict)
        assert raised.value.details["retry_after"] >= 1

    async def test_it_fails_open_when_redis_is_gone(self) -> None:
        """ADR-0017 §3. A rate limiter is not an access control, and the cost
        ceiling is a PostgreSQL rollup that survives this. Failing closed would
        turn a cache outage into a total outage for every merchant."""
        limiter = RateLimiter(_FakeRedis(broken=True), window_s=60)
        verdict = await limiter.check([Subject("tenant", "t", 1)])
        assert verdict.allowed is True

        no_redis = RateLimiter(None, window_s=60)
        assert (await no_redis.check([Subject("tenant", "t", 1)])).allowed is True

    async def test_the_window_rolls_over(self) -> None:
        redis = _FakeRedis()
        limiter = RateLimiter(redis, window_s=60)
        first = await limiter.check([Subject("tenant", "t", 1)], now=59.0)
        second = await limiter.check([Subject("tenant", "t", 1)], now=61.0)
        assert first.allowed and second.allowed


class TestTrustedProxyHops:
    def test_the_forwarded_header_is_ignored_by_default(self) -> None:
        """``X-Forwarded-For`` is attacker-controlled. Trusting it makes the
        narrowest subject free to rotate, and the limiter carries on reporting
        plausible numbers while enforcing nothing."""
        from neura_api.dependencies import client_address

        assert get_settings().trusted_proxy_hops == 0
        request = _StubRequest({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}, peer="10.0.0.1")
        assert client_address(request) == "10.0.0.1"  # type: ignore[arg-type]


class _StubPeer:
    def __init__(self, host: str) -> None:
        self.host = host


class _StubRequest:
    def __init__(self, headers: dict[str, str], *, peer: str) -> None:
        self.headers = headers
        self.client = _StubPeer(peer)


# ── Envelopes and cursors ────────────────────────────────────────────────────


class TestEnvelopes:
    def test_success_has_exactly_data_and_meta(self) -> None:
        body = envelope({"reply": "hi"}, request_id="req_1")
        assert set(body) == {"data", "meta"}
        assert body["meta"]["request_id"] == "req_1"

    def test_has_more_is_derived_from_the_cursor(self) -> None:
        """Two fields that must agree are two fields that will eventually
        disagree."""
        assert page([], next_cursor=None)["meta"]["has_more"] is False
        assert page([1], next_cursor="abc")["meta"]["has_more"] is True

    def test_a_cursor_round_trips(self) -> None:
        cursor = encode_cursor({"u": "2026-08-03T00:00:00+00:00", "i": "cnv_1"})
        assert decode_cursor(cursor) == {"u": "2026-08-03T00:00:00+00:00", "i": "cnv_1"}

    def test_a_client_cannot_read_a_cursor(self) -> None:
        assert "cnv_1" not in encode_cursor({"i": "cnv_1"})

    def test_a_malformed_cursor_is_refused_rather_than_ignored(self) -> None:
        """Silently restarting from page one makes a paginating client loop
        forever while looking like it is making progress."""
        with pytest.raises(ValidationError):
            decode_cursor("not-a-cursor!!")

    def test_no_cursor_means_the_first_page(self) -> None:
        assert decode_cursor(None) is None


# ── Outbound webhooks ────────────────────────────────────────────────────────


class TestWebhookSigning:
    def test_the_timestamp_is_inside_the_signature(self) -> None:
        """Without it a captured request replays forever, because the signature
        stays valid."""
        body = b'{"event":"conversation.resolved"}'
        signature, timestamp = sign(body, "shh")

        assert matches(body, signature, "shh", timestamp=timestamp)
        assert not matches(body, signature, "shh", timestamp=timestamp + 1)

    def test_a_different_body_does_not_verify(self) -> None:
        signature, timestamp = sign(b"a", "shh")
        assert not matches(b"b", signature, "shh", timestamp=timestamp)

    def test_the_tolerance_window_bounds_replay(self) -> None:
        now = int(datetime.now(UTC).timestamp())
        assert within_tolerance(now - 60, now=now)
        assert not within_tolerance(now - 3600, now=now)

    def test_both_directions_share_one_implementation(self) -> None:
        """The inbound verifier and the outbound signer must never diverge —
        the divergence shows up as an integration that mysteriously stops
        verifying."""
        from neura_adapters.generic import webhooks as inbound
        from neura_core.webhooks import signing as outbound

        assert inbound.sign is outbound.sign
        assert inbound.SIGNATURE_HEADER == outbound.SIGNATURE_HEADER


class TestWebhookRetrySchedule:
    def test_the_backoff_doubles(self) -> None:
        assert backoff_for(1) == timedelta(seconds=30)
        assert backoff_for(2) == timedelta(seconds=60)
        assert backoff_for(6) == timedelta(seconds=960)

    def test_seven_attempts_span_about_half_an_hour(self) -> None:
        """Long enough for a merchant's brief deploy, short enough that a dead
        endpoint is declared dead while somebody remembers changing it."""
        total = sum(backoff_for(n).total_seconds() for n in range(1, MAX_ATTEMPTS))
        assert 1800 <= total <= 2100

    def test_the_event_list_has_no_event_that_cannot_fire(self) -> None:
        """``agent.action.pending_approval`` is in api-design.md §9 and is
        deliberately absent: no WRITE tool can be registered (ADR-0010), so the
        approval queue it names does not exist. A subscribable event that can
        never occur is a feature a merchant configures and then stops trusting
        the rest of the list because of."""
        assert "agent.action.pending_approval" not in {e.value for e in WebhookEvent}

    def test_delivery_statuses_distinguish_dead_from_pending(self) -> None:
        assert DeliveryStatus.DEAD.value == "dead"
        assert DeliveryStatus.PENDING.value == "pending"


# ── The eval target and the runner stay in step ──────────────────────────────


class TestBothCallersReadTheSameFlags:
    def test_the_eval_target_and_the_runner_agree_on_escalation(self) -> None:
        """Both map the graph's own flags, never the reply text. A model can
        apologise politely while a tool ran anyway."""
        final: dict[str, Any] = {
            "reply": "Let me get someone",
            "escalated": True,
            "escalation_reason": "ownership unproven",
        }
        assert _outcome(final).escalated is True
        assert _outcome(final).state is ConversationState.ESCALATED

    def test_the_target_still_builds(self) -> None:
        """A smoke check that the two callers have not drifted apart in a way
        that stops one of them constructing."""
        assert CareTarget(llm=object()).name.startswith("care@")
