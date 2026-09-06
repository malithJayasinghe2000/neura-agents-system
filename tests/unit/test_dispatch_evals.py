"""Measuring a target that is not an agent — [ADR-0031] §6.

Every golden dataset in this repository lives inside an agent package, and the
dispatcher belongs to no agent. Discovery never actually required a target to
*be* one — only the dataset convention did — so what is asserted here is that
the seam holds, that dispatch is scored, and that the two ways to be wrong stay
distinguishable.

No model, no database, no store.
"""

from __future__ import annotations

import asyncio

import pytest
from neura_evals.dataset import EvalCase, Expectation, load_all
from neura_evals.discovery import discover_agents
from neura_evals.metrics import EXPENSIVE_MISS, CaseOutcome, score_case, summarise
from neura_evals.target import AgentResponse

from neura_dispatch.evals import DispatchTarget, build_target

DATASETS = next(a for a in discover_agents() if a.key == "dispatch").dataset_dir


def _case(case_id: str, expected: str, tags: list[str] | None = None) -> EvalCase:
    return EvalCase(
        id=case_id,
        intent="dispatch",
        input="a shopper said something",
        expect=Expectation(agent=expected),
        synthetic=True,
        tags=tags or [],
    )


def _score(case: EvalCase, response: AgentResponse) -> object:
    return asyncio.run(score_case(case, response, None))


class TestTheTargetIsDiscoverable:
    def test_dispatch_registers_beside_the_agents(self) -> None:
        """The whole point of §6: same mechanism, no agent required."""
        assert "dispatch" in {a.key for a in discover_agents()}

    def test_its_datasets_are_found(self) -> None:
        assert DATASETS.is_dir()
        assert list(DATASETS.glob("*.yaml"))

    def test_an_unreachable_model_is_unmeasured_not_a_misroute(self) -> None:
        """The step-2 version of this test asserted the target was a stub.

        It is not one any more, and what replaces it is the assertion that
        matters: with no usable client the case is `infrastructure_error` —
        **skipped, not scored** — because a dead provider recorded as a wrong
        answer is the 2026-07-31 mistake, where Ollama died and the suite
        reported a total agent collapse (E6).
        """
        response = asyncio.run(build_target(None).run(_case("x", "care")))
        assert response.infrastructure_error
        assert response.dispatched_to is None
        assert not response.not_run

    def test_that_case_is_errored_rather_than_failed_or_passed(self) -> None:
        """The half above is only true if the scorer agrees with it.

        **This asserted `result.passed` until 2026-09-06**, and it was half
        right — the half that matters here is that a dead provider is not
        recorded as a misroute. The missing half is that it is not a *pass*
        either, which is how 47 unreachable cases reported `47 passed, 0 failed`
        ([ADR-0036], E9). The case is `ERRORED`: neither.
        """
        response = asyncio.run(build_target(None).run(_case("x", "care")))
        result = _score(_case("x", "care"), response)
        assert result.outcome is CaseOutcome.ERRORED  # type: ignore[attr-defined]
        assert not result.passed and not result.failed  # type: ignore[attr-defined]
        assert all(c.status.value == "skip" for c in result.checks)  # type: ignore[attr-defined]

    def test_the_target_satisfies_the_harness_protocol(self) -> None:
        assert isinstance(build_target(None), DispatchTarget)
        assert hasattr(build_target(None), "name")


class TestDispatchIsScored:
    def test_the_right_agent_passes(self) -> None:
        result = _score(_case("a", "care"), AgentResponse(reply="", dispatched_to="care"))
        assert result.passed  # type: ignore[attr-defined]

    def test_the_wrong_agent_fails(self) -> None:
        result = _score(_case("a", "care"), AgentResponse(reply="", dispatched_to="sell"))
        assert not result.passed  # type: ignore[attr-defined]

    def test_dispatching_to_nobody_fails(self) -> None:
        """Distinct from picking wrong, and it must not be silently skipped.

        `dispatched_to` is None on every ordinary agent run, so a dispatch case
        handed to a single agent would otherwise pass having dispatched nothing
        — the `tool_selection_accuracy` failure of 2026-08-27, rebuilt.
        """
        result = _score(_case("a", "care"), AgentResponse(reply="", dispatched_to=None))
        assert not result.passed  # type: ignore[attr-defined]

    def test_a_dispatch_case_is_exempt_from_the_zero_tool_rule(self) -> None:
        """A chooser has no tools, so `tools_called: []` would be a category error."""
        result = _score(_case("a", "care"), AgentResponse(reply="", dispatched_to="care"))
        names = {c.name for c in result.checks}  # type: ignore[attr-defined]
        assert "tool_selection" not in names

    def test_an_ordinary_zero_tool_case_still_fails(self) -> None:
        """The exemption must not have widened the hole it sits next to."""
        plain = EvalCase(
            id="p", intent="product_qa", input="q", expect=Expectation(), synthetic=True
        )
        result = _score(plain, AgentResponse(reply="something"))
        assert not result.passed  # type: ignore[attr-defined]


class TestTheAsymmetryStaysVisible:
    """A single accuracy figure reports both directions identically.

    One loses a product card; the other hands the shopper to a person.
    """

    def _run(self) -> object:
        results = [
            _score(_case("a", "care"), AgentResponse(reply="", dispatched_to="care")),
            _score(_case("b", "care"), AgentResponse(reply="", dispatched_to="sell")),
            _score(_case("c", "sell"), AgentResponse(reply="", dispatched_to="care")),
            _score(_case("d", "sell"), AgentResponse(reply="", dispatched_to="sell")),
        ]
        return summarise(results)  # type: ignore[arg-type]

    def test_accuracy_is_reported(self) -> None:
        summary = self._run()
        assert summary.metrics["dispatch_accuracy"] == 0.5  # type: ignore[attr-defined]

    def test_the_matrix_names_both_directions(self) -> None:
        summary = self._run()
        assert summary.dispatch_matrix == {  # type: ignore[attr-defined]
            "care": {"care": 1, "sell": 1},
            "sell": {"care": 1, "sell": 1},
        }

    def test_accuracy_alone_cannot_distinguish_them(self) -> None:
        """The reason the matrix exists, asserted rather than argued.

        Two runs with opposite failures produce the same rate.
        """
        one = summarise(  # type: ignore[arg-type]
            [_score(_case("a", "care"), AgentResponse(reply="", dispatched_to="sell"))]
        )
        other = summarise(  # type: ignore[arg-type]
            [_score(_case("b", "sell"), AgentResponse(reply="", dispatched_to="care"))]
        )
        assert one.metrics["dispatch_accuracy"] == other.metrics["dispatch_accuracy"] == 0.0
        assert one.dispatch_matrix != other.dispatch_matrix

    def test_dispatch_accuracy_is_still_not_gated(self) -> None:
        """ADR-0033 §5 — and now for a stated reason rather than a pending one.

        One rate reports a lost product card and a summoned human identically.
        The gate lives on ``expensive_misroute_rate`` instead, which covers only
        the half where there is no product judgement.
        """
        from neura_evals.metrics import THRESHOLDS

        assert "dispatch_accuracy" not in THRESHOLDS


class TestTheExpensiveDirectionIsGated:
    """ADR-0033 §3. The gate is zero, and it is on the declared half only."""

    def test_the_gate_is_zero_and_an_upper_bound(self) -> None:
        from neura_evals.metrics import LOWER_IS_BETTER, THRESHOLDS

        assert THRESHOLDS["expensive_misroute_rate"] == 0.0
        assert "expensive_misroute_rate" in LOWER_IS_BETTER

    def test_one_expensive_misroute_breaches_the_gate(self) -> None:
        summary = summarise(  # type: ignore[arg-type]
            [
                _score(
                    _case("a", "care", tags=["care", EXPENSIVE_MISS]),
                    AgentResponse(reply="", dispatched_to="sell"),
                ),
                _score(
                    _case("b", "care", tags=["care", EXPENSIVE_MISS]),
                    AgentResponse(reply="", dispatched_to="care"),
                ),
            ]
        )
        assert summary.metrics["expensive_misroute_rate"] == 0.5
        assert [name for name, _, _ in summary.gate_failures()] == ["expensive_misroute_rate"]

    def test_the_cheap_direction_does_not_breach_it(self) -> None:
        """A `sell -> care` miss is a lost product card, not a summoned human.

        The rate must stay 0.00 while `dispatch_accuracy` falls, or the gate has
        quietly become the flat rate ADR-0033 §5 refuses to gate.
        """
        summary = summarise(  # type: ignore[arg-type]
            [
                _score(
                    _case("a", "care", tags=["care", EXPENSIVE_MISS]),
                    AgentResponse(reply="", dispatched_to="care"),
                ),
                _score(
                    _case("b", "sell", tags=["sell"]),
                    AgentResponse(reply="", dispatched_to="care"),
                ),
            ]
        )
        assert summary.metrics["dispatch_accuracy"] == 0.5
        assert summary.metrics["expensive_misroute_rate"] == 0.0
        assert summary.gate_failures() == []

    def test_a_suite_that_tags_nothing_reports_nothing(self) -> None:
        """Rather than a vacuous 0.00 that would pass the gate by measuring none.

        This is `tool_selection_accuracy`'s 2026-08-27 failure — a rate computed
        from one case of fourteen and reported as if it covered the suite.
        """
        summary = summarise(  # type: ignore[arg-type]
            [_score(_case("a", "care"), AgentResponse(reply="", dispatched_to="sell"))]
        )
        assert "expensive_misroute_rate" not in summary.metrics

    def test_the_shipping_dataset_tags_its_determined_half(self) -> None:
        """The gate is worth nothing if the dataset stops declaring severity."""
        from pathlib import Path

        from neura_evals.dataset import load_dataset

        path = (
            Path(__file__).resolve().parents[2]
            / "packages/neura-dispatch/src/neura_dispatch/evals/datasets/dispatch.yaml"
        )
        cases = load_dataset(path).cases
        tagged = [c for c in cases if EXPENSIVE_MISS in c.tags]

        assert len(tagged) == 10
        # Every tagged case is one SELL answers by fetching a person. Asserted
        # here, in the dataset's own package's test, and deliberately NOT in
        # `metrics.py` — that module must not learn the word "care".
        assert {c.expect.agent for c in tagged} == {"care"}


class TestNothingRanIsNotEverythingPassed:
    """Found while building §6, and it was general rather than ours.

    The caveat keyed on the target being *named* ``no-agent``, so the first
    target that was neither an agent nor ``--no-agent`` printed
    ``16 passed, 0 failed`` with no warning at all.
    """

    def test_unmeasured_cases_are_counted(self) -> None:
        results = [
            _score(_case("a", "care"), AgentResponse(reply="", not_run=True, error="unbuilt"))
            for _ in range(3)
        ]
        summary = summarise(results)  # type: ignore[arg-type]
        assert summary.unmeasured == 3
        assert summary.total == 3

    def test_a_measured_run_counts_none(self) -> None:
        summary = summarise(  # type: ignore[arg-type]
            [_score(_case("a", "care"), AgentResponse(reply="", dispatched_to="care"))]
        )
        assert summary.unmeasured == 0


class TestTheDatasetSaysWhatItIs:
    @pytest.mark.parametrize("dataset", load_all(DATASETS), ids=lambda d: d.name)
    def test_every_case_is_marked_synthetic(self, dataset: object) -> None:
        """None of these came from a real conversation (E1, B2)."""
        assert dataset.is_fully_synthetic  # type: ignore[attr-defined]

    @pytest.mark.parametrize("dataset", load_all(DATASETS), ids=lambda d: d.name)
    def test_every_case_asserts_a_dispatch(self, dataset: object) -> None:
        for case in dataset.cases:  # type: ignore[attr-defined]
            assert case.expect.agent, f"{case.id} asserts no agent — it scores nothing"

    @pytest.mark.parametrize("dataset", load_all(DATASETS), ids=lambda d: d.name)
    def test_both_directions_are_represented(self, dataset: object) -> None:
        """A dataset of one expected agent measures a target that always says it."""
        expected = {c.expect.agent for c in dataset.cases}  # type: ignore[attr-defined]
        assert len(expected) >= 2, f"only ever expects {expected}"
