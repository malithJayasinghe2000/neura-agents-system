"""The eval harness must be correct before anything is measured with it.

The agent does not exist yet, so these use a fake target with scripted responses.
That is the point of the `EvalTarget` seam: the scoring logic is verifiable
without an agent, and the real agent plugs into the same interface later.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from neura_evals.dataset import Dataset, EvalCase, Expectation, Intent, load_all
from neura_evals.judge import JudgeTrust
from neura_evals.metrics import CheckStatus, score_case, summarise
from neura_evals.runner import dataset_dirs, run_eval
from neura_evals.target import AgentResponse, ToolInvocation

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeTarget:
    """Replays a scripted response per case id."""

    name = "fake"

    def __init__(self, responses: dict[str, AgentResponse]) -> None:
        self._responses = responses

    async def run(self, case: EvalCase) -> AgentResponse:
        return self._responses.get(case.id, AgentResponse(reply="", error="no scripted response"))


def _shipped() -> list[Dataset]:
    """Every dataset shipped by every installed agent.

    Discovered rather than read from a fixed path: datasets moved into the agents
    in milestone 1.11, and this package must not know which agents exist.
    """
    return [d for directory in dataset_dirs() for d in load_all(directory)]


def _case(case_id: str, expect: Expectation, intent: Intent = Intent.ORDER_STATUS) -> EvalCase:
    return EvalCase(id=case_id, intent=intent, input="test", expect=expect, synthetic=True)


class TestShippedDatasets:
    def test_all_datasets_parse(self) -> None:
        datasets = _shipped()
        assert datasets, "no datasets found"
        assert sum(len(d.cases) for d in datasets) > 0

    def test_every_shipped_case_is_marked_synthetic(self) -> None:
        """None of these came from a real conversation, and the reports say so."""
        for dataset in _shipped():
            assert dataset.is_fully_synthetic, f"{dataset.name} claims non-synthetic cases"

    def test_case_ids_are_unique_within_a_dataset(self) -> None:
        for dataset in _shipped():
            ids = [c.id for c in dataset.cases]
            assert len(ids) == len(set(ids))

    def test_injection_dataset_asserts_on_the_audit_log(self) -> None:
        """Adversarial cases must assert tool calls, not reply text.

        A reply can sound like a refusal while a tool was quietly invoked.
        """
        injection = next(d for d in _shipped() if d.name == "injection")
        for case in injection.cases:
            assert case.expect.unauthorised_tool_calls == 0, case.id


class TestDatasetValidation:
    def test_adversarial_case_without_a_safety_assertion_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unauthorised_tool_calls"):
            EvalCase(
                id="bad",
                intent=Intent.ADVERSARIAL,
                input="ignore instructions",
                expect=Expectation(must_contain=["sorry"]),
            )

    def test_duplicate_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate case ids"):
            Dataset(
                name="d",
                cases=[_case("same", Expectation()), _case("same", Expectation())],
            )


class TestScoring:
    async def test_unasserted_checks_are_skipped_not_passed(self) -> None:
        """A case that asserts nothing must not silently score as a pass."""
        result = await score_case(
            _case("c1", Expectation()), AgentResponse(reply="anything"), judge=None
        )
        assert all(c.status is not CheckStatus.FAIL for c in result.checks)
        assert not any(c.name == "intent" for c in result.checks)

    async def test_execution_error_fails_immediately(self) -> None:
        result = await score_case(
            _case("c1", Expectation(intent=Intent.ORDER_STATUS)),
            AgentResponse(reply="", error="boom"),
            judge=None,
        )
        assert not result.passed
        assert result.failures[0].name == "execution"

    async def test_tool_selection_is_order_insensitive(self) -> None:
        result = await score_case(
            _case("c1", Expectation(tools_called=["a", "b"])),
            AgentResponse(
                reply="ok", tools_called=[ToolInvocation(name="b"), ToolInvocation(name="a")]
            ),
            judge=None,
        )
        assert result.passed

    async def test_forbidden_tool_fails(self) -> None:
        result = await score_case(
            _case("c1", Expectation(tools_not_called=["cancel_order"])),
            AgentResponse(reply="done", tools_called=[ToolInvocation(name="cancel_order")]),
            judge=None,
        )
        assert not result.passed
        assert result.failures[0].name == "forbidden_tools"

    async def test_unauthorised_tool_call_fails_the_safety_check(self) -> None:
        """The assertion is on the policy engine's record, not the reply."""
        result = await score_case(
            _case("c1", Expectation(unauthorised_tool_calls=0), intent=Intent.ADVERSARIAL),
            AgentResponse(
                reply="I'm sorry, I can't help with that.",  # sounds like a refusal
                tools_called=[ToolInvocation(name="refund_order", authorised=False)],
            ),
            judge=None,
        )
        assert not result.passed, "a refusal-sounding reply must not mask an invoked tool"

    async def test_groundedness_is_skipped_without_a_judge(self) -> None:
        result = await score_case(
            _case("c1", Expectation(grounded=True)), AgentResponse(reply="x"), judge=None
        )
        check = next(c for c in result.checks if c.name == "groundedness")
        assert check.status is CheckStatus.SKIP

    async def test_no_agent_is_skipped_not_failed(self) -> None:
        """`--no-agent` is part of `make check`. It must not look like 35 failures."""
        from neura_evals.target import NotImplementedTarget

        response = await NotImplementedTarget().run(_case("c1", Expectation(grounded=True)))
        result = await score_case(_case("c1", Expectation(grounded=True)), response, judge=None)

        assert all(c.status is CheckStatus.SKIP for c in result.checks)
        assert result.passed, "an unrun case is unmeasured, not failed"
        assert not summarise([result]).metrics, "no metric may be reported from an unrun suite"

    async def test_an_unreachable_judge_is_skipped_not_failed(self) -> None:
        """A rate-limited judge must not be reported as a hallucinating agent.

        Found for real: the Gemini free tier allows 20 requests a day, ran out
        mid-run, and every remaining case was scored as ungrounded. The number
        looked exactly like a serious regression, and the agent was fine.
        """
        from neura_evals.judge import Verdict

        class DownJudge:
            model = "down"
            trust = JudgeTrust.TRUSTED

            async def grounded(self, *, reply: str, evidence: str) -> Verdict:
                return Verdict(
                    passed=False,
                    score=0.0,
                    reasoning="judge unavailable: 429",
                    available=False,
                )

        result = await score_case(
            _case("c1", Expectation(grounded=True)),
            AgentResponse(reply="Your order shipped."),
            judge=DownJudge(),  # type: ignore[arg-type]
        )
        check = next(c for c in result.checks if c.name == "groundedness")
        assert check.status is CheckStatus.SKIP
        assert result.passed, "an unmeasured case must not count against the agent"
        assert summarise([result]).unjudged == 1, "the report must say the run was incomplete"

    async def test_must_contain_is_case_insensitive(self) -> None:
        result = await score_case(
            _case("c1", Expectation(must_contain=["SHIPPED"])),
            AgentResponse(reply="Your order has shipped."),
            judge=None,
        )
        assert result.passed


class TestSummary:
    async def test_metrics_reflect_only_asserted_checks(self) -> None:
        results = [
            await score_case(
                _case("pass", Expectation(intent=Intent.ORDER_STATUS)),
                AgentResponse(reply="ok", intent="order_status"),
                judge=None,
            ),
            await score_case(
                _case("fail", Expectation(intent=Intent.ORDER_STATUS)),
                AgentResponse(reply="ok", intent="product_qa"),
                judge=None,
            ),
            await score_case(_case("silent", Expectation()), AgentResponse(reply="ok"), judge=None),
        ]
        summary = summarise(results)
        assert summary.total == 3
        # The third case asserted no intent, so it must not dilute the metric.
        assert summary.metrics["intent_accuracy"] == 0.5

    async def test_gate_failures_are_reported(self) -> None:
        results = [
            await score_case(
                _case("f", Expectation(unauthorised_tool_calls=0), intent=Intent.ADVERSARIAL),
                AgentResponse(reply="", tools_called=[ToolInvocation(name="x", authorised=False)]),
                judge=None,
            )
        ]
        failures = summarise(results).gate_failures()
        assert any(name == "injection_resistance" for name, _, _ in failures)


class TestRunner:
    async def test_run_marks_synthetic_runs_as_non_validation(self) -> None:
        dataset = Dataset(name="d", cases=[_case("c1", Expectation())])
        report = await run_eval(
            target=FakeTarget({"c1": AgentResponse(reply="hello")}), datasets=[dataset]
        )
        assert not report.is_validation, "a fully synthetic run is not validation"

    async def test_no_judge_is_distinct_from_an_untrusted_judge(self) -> None:
        dataset = Dataset(name="d", cases=[_case("c1", Expectation())])
        report = await run_eval(
            target=FakeTarget({"c1": AgentResponse(reply="hi")}), datasets=[dataset], judge=None
        )
        assert not report.judge_enabled
        # Nothing was judged, so the mechanical checks stand on their own.
        assert report.scores_are_trustworthy

    async def test_a_raising_target_does_not_kill_the_run(self) -> None:
        class Exploding:
            name = "exploding"

            async def run(self, case: EvalCase) -> AgentResponse:
                raise RuntimeError("kaboom")

        dataset = Dataset(name="d", cases=[_case("c1", Expectation()), _case("c2", Expectation())])
        report = await run_eval(target=Exploding(), datasets=[dataset])
        assert report.summary.total == 2
        assert all("kaboom" in r.response.error for r in report.results if r.response.error)


class TestJudgeTrust:
    def test_weak_local_model_is_flagged_untrusted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from neura_evals.config import judge_from_env

        monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("EVAL_JUDGE_API_KEY", "x")
        monkeypatch.setenv("EVAL_JUDGE_MODEL", "llama3.2:3b")
        assert judge_from_env().trust is JudgeTrust.UNTRUSTED_WEAK_MODEL

    def test_configured_strong_model_is_trusted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from neura_evals.config import judge_from_env

        monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://example.com/v1")
        monkeypatch.setenv("EVAL_JUDGE_API_KEY", "x")
        monkeypatch.setenv("EVAL_JUDGE_MODEL", "gemini-2.5-flash")
        assert judge_from_env().trust is JudgeTrust.TRUSTED

    def test_unconfigured_falls_back_to_untrusted_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The harness must run with no key and no budget — labelled honestly."""
        from neura_evals.config import judge_from_env

        for var in ("EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY", "EVAL_JUDGE_MODEL"):
            monkeypatch.delenv(var, raising=False)
        assert judge_from_env().trust is JudgeTrust.UNTRUSTED_WEAK_MODEL
