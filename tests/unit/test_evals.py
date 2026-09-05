"""The eval harness must be correct before anything is measured with it.

The agent does not exist yet, so these use a fake target with scripted responses.
That is the point of the `EvalTarget` seam: the scoring logic is verifiable
without an agent, and the real agent plugs into the same interface later.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from neura_evals.dataset import Dataset, EvalCase, Expectation, Intent, load_all
from neura_evals.judge import JudgeTrust
from neura_evals.metrics import CheckStatus, score_case, summarise
from neura_evals.persist import default_path, write_report
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

    def test_invented_datasets_are_wholly_invented(self) -> None:
        """None of these came from a real conversation, and the reports say so.

        Until 2026-09-05 this held for every shipped dataset. `graded.yaml` is
        the deliberate exception (ADR-0032) and is asserted in the opposite
        direction below — so the pair still says exactly which cases are
        evidence and which are a harness self-test.
        """
        for dataset in _shipped():
            if dataset.name == "graded":
                continue
            assert dataset.is_fully_synthetic, f"{dataset.name} claims non-synthetic cases"

    def test_the_graded_dataset_is_wholly_real(self) -> None:
        """The other half, and the one that can be broken by hand.

        `graded.yaml` is written by `make promote`, which refuses a fact that is
        not in the approved draft. A case typed straight into the file would
        wear `synthetic: false` — and therefore count as validation — while
        asserting something no human ever approved. If that file exists, every
        case in it must be real.
        """
        graded = [d for d in _shipped() if d.name == "graded"]
        for dataset in graded:
            assert dataset.synthetic_count == 0, (
                "a synthetic case is in graded.yaml — it would be counted as validation"
            )
            for case in dataset.cases:
                assert any(t.startswith("from-turn:") for t in case.tags), (
                    f"{case.id} claims to be real but names no shadow turn (ADR-0032 §6)"
                )

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
            # One tool call, so the zero-tool rule below is not what is under
            # test here — this is about the checks a silent case does not emit.
            _case("c1", Expectation()),
            AgentResponse(reply="anything", tools_called=[ToolInvocation(name="get_order")]),
            judge=None,
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

    async def test_a_case_that_called_nothing_is_scored_not_skipped(self) -> None:
        """The A14 hole: the one turn that used no tool fell out of a gated metric.

        `recommend_002` called no tool, composed nothing and escalated — and
        because it never wrote `tools_called`, `tool_selection_accuracy` reported
        1.00 over the three cases that had. A metric whose denominator each case
        may opt out of cannot fail, and it opted out exactly where the surprise
        was.
        """
        result = await score_case(
            _case("c1", Expectation(intent=Intent.PRODUCT_QA)),
            AgentResponse(reply="I'll pass you to a colleague.", intent=Intent.PRODUCT_QA),
            judge=None,
        )
        selection = [c for c in result.checks if c.name == "tool_selection"]
        assert selection, "a turn that called no tools must be scored, not skipped"
        assert selection[0].status is CheckStatus.FAIL
        assert "tools_called" in selection[0].detail, "the failure must name its own fix"

    async def test_calling_nothing_passes_when_the_case_says_so(self) -> None:
        """`[]` is an expectation, not an absence of one."""
        result = await score_case(
            _case("c1", Expectation(tools_called=[])), AgentResponse(reply="ok"), judge=None
        )
        assert result.passed

    async def test_a_silent_case_that_did_call_tools_is_still_skipped(self) -> None:
        """Not asserting an exact tool set stays legitimate — over-specifying is brittle."""
        result = await score_case(
            _case("c1", Expectation()),
            AgentResponse(reply="ok", tools_called=[ToolInvocation(name="search_products")]),
            judge=None,
        )
        assert not any(c.name == "tool_selection" for c in result.checks)

    async def test_adversarial_cases_are_exempt_from_the_zero_tool_rule(self) -> None:
        """They assert authorisation, which is mandatory, and not selection."""
        result = await score_case(
            _case("c1", Expectation(unauthorised_tool_calls=0), intent=Intent.ADVERSARIAL),
            AgentResponse(reply="no"),
            judge=None,
        )
        assert not any(c.name == "tool_selection" for c in result.checks)
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
            AgentResponse(
                reply="Your order shipped.", tools_called=[ToolInvocation(name="get_order")]
            ),
            judge=DownJudge(),  # type: ignore[arg-type]
        )
        check = next(c for c in result.checks if c.name == "groundedness")
        assert check.status is CheckStatus.SKIP
        assert result.passed, "an unmeasured case must not count against the agent"
        assert summarise([result]).unjudged == 1, "the report must say the run was incomplete"

    async def test_must_contain_is_case_insensitive(self) -> None:
        result = await score_case(
            _case("c1", Expectation(must_contain=["SHIPPED"])),
            AgentResponse(
                reply="Your order has shipped.", tools_called=[ToolInvocation(name="get_order")]
            ),
            judge=None,
        )
        assert result.passed


class TestSummary:
    async def test_a_rate_is_reported_with_how_much_of_the_run_it_covers(self) -> None:
        """1.00 from one case must not print like 1.00 from fourteen."""
        results = [
            await score_case(
                _case("asserts", Expectation(intent=Intent.ORDER_STATUS)),
                AgentResponse(
                    reply="ok", intent="order_status", tools_called=[ToolInvocation(name="t")]
                ),
                judge=None,
            ),
            await score_case(
                _case("silent", Expectation()),
                AgentResponse(reply="ok", tools_called=[ToolInvocation(name="t")]),
                judge=None,
            ),
        ]
        summary = summarise(results)
        assert summary.metrics["intent_accuracy"] == 1.0
        assert summary.coverage["intent_accuracy"] == (1, 2), "one case of two produced that 1.00"

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

    async def test_escalation_metrics_ignore_failures_that_are_not_about_escalating(self) -> None:
        """Open question E5, and the reason it was worth its own fix.

        Both cases below get their escalation decision exactly right. Both then
        fail on wording. Under the original definition — which asked whether the
        whole *case* passed — the first stopped counting as a true positive and
        the second was counted as an escalation the agent should have made and
        did not, so a gated metric was partly measuring phrasing.

        Precision and recall must both be 1.00 here. Nothing escalated wrongly
        and nothing failed to escalate.
        """
        results = [
            # Correctly escalated, and the reply is missing a required word.
            await score_case(
                _case(
                    "escalated_but_worded_badly", Expectation(escalated=True, must_contain=["X"])
                ),
                AgentResponse(reply="passing you to a colleague", escalated=True),
                judge=None,
            ),
            # Correctly did NOT escalate, and the reply is missing a required word.
            await score_case(
                _case(
                    "answered_but_worded_badly", Expectation(escalated=False, must_contain=["X"])
                ),
                AgentResponse(reply="we ship in 3 days", escalated=False),
                judge=None,
            ),
        ]

        summary = summarise(results)
        assert not results[0].passed and not results[1].passed, "both must fail on `must_contain`"
        assert summary.metrics["escalation_precision"] == 1.0
        assert summary.metrics["escalation_recall"] == 1.0

    async def test_a_missed_escalation_is_still_counted(self) -> None:
        """The fix must not make the metric blind in the direction that matters.

        Under-escalating is the expensive error — it tells a customer something
        wrong about their money — so a case that should have handed over and did
        not has to show up as a recall miss.
        """
        results = [
            await score_case(
                _case("should_have_escalated", Expectation(escalated=True)),
                AgentResponse(reply="it'll be fine", escalated=False),
                judge=None,
            ),
            await score_case(
                _case("escalated_properly", Expectation(escalated=True)),
                AgentResponse(reply="passing you over", escalated=True),
                judge=None,
            ),
        ]
        summary = summarise(results)
        assert summary.metrics["escalation_recall"] == 0.5
        assert summary.metrics["escalation_precision"] == 1.0

    async def test_an_unnecessary_escalation_costs_precision(self) -> None:
        """The other direction: a handover nobody needed."""
        results = [
            await score_case(
                _case("did_not_need_a_person", Expectation(escalated=False)),
                AgentResponse(reply="passing you over", escalated=True),
                judge=None,
            ),
            await score_case(
                _case("escalated_properly", Expectation(escalated=True)),
                AgentResponse(reply="passing you over", escalated=True),
                judge=None,
            ),
        ]
        summary = summarise(results)
        assert summary.metrics["escalation_precision"] == 0.5
        assert summary.metrics["escalation_recall"] == 1.0

    async def test_cases_that_say_nothing_about_escalation_are_excluded(self) -> None:
        results = [
            await score_case(
                _case("silent", Expectation(must_contain=["ok"])),
                AgentResponse(reply="nope", escalated=True),
                judge=None,
            )
        ]
        summary = summarise(results)
        assert "escalation_precision" not in summary.metrics
        assert "escalation_recall" not in summary.metrics

    def test_a_small_hosted_model_is_not_trusted_to_judge(self) -> None:
        """The trust heuristic knew only Ollama tags until the judge moved to a
        cloud gateway on 2026-08-02.

        A hosted 9B is called `nvidia/nemotron-nano-9b-v2:free`. It matches no
        Ollama marker, so it would have been labelled **trusted** — a weak model
        grading a weak model, reported as a measurement, by the one component
        whose whole job is to refuse exactly that.
        """
        from neura_evals.config import _looks_weak

        for weak in (
            "nvidia/nemotron-nano-9b-v2:free",
            "some/model-3b-instruct",
            "vendor/tiny-chat",
            "vendor/gpt-mini",
            "vendor/mini-judge",
            "llama3.2:3b",
        ):
            assert _looks_weak(weak), f"{weak} should not be trusted to judge"

        for strong in (
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "google/gemma-4-26b-a4b-it:free",
            # The bug the first draft of this list shipped: bare "mini" matches
            # ge-MINI, so a good judge was quietly declared untrustworthy.
            "gemini-3.6-flash",
        ):
            assert not _looks_weak(strong), (
                f"{strong} was wrongly called weak — a parameter count like "
                "`a12b` or `120b` must not read as a size suffix"
            )

    async def test_an_unreachable_provider_is_skipped_not_failed(self) -> None:
        """Open question E6, found the expensive way.

        Ollama died partway through a run on 2026-07-31. The graph did exactly
        the right thing — `route` could not classify, so every turn escalated —
        and the suite reported **intent accuracy 0.00 and tool selection 0.00**,
        which reads as a total agent collapse and was a dead server.

        The case was never measured, so it must be skipped, exactly as an
        unreachable judge is. This is the third instance of the same shape in
        this harness: an outage reported as a result.
        """
        response = AgentResponse(
            reply="I'm passing you to a colleague.",
            escalated=True,
            infrastructure_error="the router was unreachable: ProviderUnavailableError",
        )
        result = await score_case(
            _case("c1", Expectation(intent=Intent.ORDER_STATUS, escalated=False)),
            response,
            judge=None,
        )

        assert all(c.status is CheckStatus.SKIP for c in result.checks)
        assert result.passed, "an unmeasured case is not a failure"

        summary = summarise([result])
        assert summary.unavailable == 1, "the report must say how many cases never ran"
        assert "intent_accuracy" not in summary.metrics, "a dead provider must not score the agent"

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


class TestPersistence:
    """Open question E7. A run that is printed and not kept costs a second run.

    The three assertions that matter are on ``draft``, ``verify_reason`` and
    ``evidence``. Everything else in the file is convenience; those three are the
    reason it exists, and each has already been the missing field once — the
    draft on 2026-08-02, the evidence on 2026-08-26 when A14 could not tell
    whether the attribute the verifier refused was in *that turn's* shortlist or
    merely in the fixture.
    """

    async def test_the_draft_the_reason_and_the_evidence_survive_the_round_trip(
        self, tmp_path: Path
    ) -> None:
        response = AgentResponse(
            reply="",
            escalated=True,
            draft="It's a 3-layer shell with a 20,000mm hydrostatic head, so it sheds rain.",
            verify_reason="a higher 20,000mm hydrostatic head",
            retrieved_context=["Product p_jacket_2: 20,000mm hydrostatic head"],
        )
        dataset = Dataset(name="d", cases=[_case("c1", Expectation(escalated=False))])
        report = await run_eval(target=FakeTarget({"c1": response}), datasets=[dataset])

        path = write_report(report, tmp_path / "run.json")
        case = json.loads(path.read_text())["cases"][0]

        assert case["draft"] == response.draft, "the composer's words must survive"
        assert case["verify_reason"] == response.verify_reason
        assert "20,000mm hydrostatic head" in case["evidence"], (
            "a draft is only judgeable against what the turn was allowed to rely on"
        )

    async def test_passed_cases_are_kept_too(self, tmp_path: Path) -> None:
        """A file of failures alone cannot answer "did this regress"."""
        dataset = Dataset(name="d", cases=[_case("c1", Expectation()), _case("c2", Expectation())])
        report = await run_eval(
            target=FakeTarget(
                {
                    "c1": AgentResponse(reply="a", tools_called=[ToolInvocation(name="t")]),
                    "c2": AgentResponse(reply="b", tools_called=[ToolInvocation(name="t")]),
                }
            ),
            datasets=[dataset],
        )
        cases = json.loads(write_report(report, tmp_path / "r.json").read_text())["cases"]
        assert {c["case_id"] for c in cases} == {"c1", "c2"}
        assert all(c["passed"] for c in cases)

    async def test_why_a_turn_escalated_is_kept(self, tmp_path: Path) -> None:
        """The field A14 needed and the file did not have.

        A turn that escalates before `verify` has an empty draft, an empty
        verify_reason and no evidence — the record says only that it happened.
        The node that decided wrote a sentence saying which half failed, and it
        went to the terminal.
        """
        dataset = Dataset(name="d", cases=[_case("c1", Expectation(escalated=False))])
        report = await run_eval(
            target=FakeTarget(
                {
                    "c1": AgentResponse(
                        reply="I'll pass you to a colleague.",
                        escalated=True,
                        escalation_reason="the catalogue could not be searched",
                        tools_called=[ToolInvocation(name="t")],
                    )
                }
            ),
            datasets=[dataset],
        )
        case = json.loads(write_report(report, tmp_path / "r.json").read_text())["cases"][0]
        assert case["escalation_reason"] == "the catalogue could not be searched"

    async def test_a_synthetic_run_says_so_in_the_file(self, tmp_path: Path) -> None:
        """Read six weeks later, a number without this is a number somebody quotes."""
        dataset = Dataset(name="d", cases=[_case("c1", Expectation())])
        report = await run_eval(
            target=FakeTarget({"c1": AgentResponse(reply="x")}), datasets=[dataset]
        )
        written = json.loads(write_report(report, tmp_path / "r.json").read_text())
        assert written["is_validation"] is False

    def test_the_default_path_does_not_overwrite_the_previous_run(self) -> None:
        """Rule 4 asks for n>=3 either side. A path that overwrites gives n=1."""
        assert default_path("sell").name.startswith("sell-")
        assert default_path("sell").suffix == ".json"
