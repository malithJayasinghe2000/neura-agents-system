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
from neura_evals.metrics import score_case, summarise
from neura_evals.target import AgentResponse

from neura_dispatch.evals import DispatchTarget, build_target

DATASETS = next(a for a in discover_agents() if a.key == "dispatch").dataset_dir


def _case(case_id: str, expected: str) -> EvalCase:
    return EvalCase(
        id=case_id,
        intent="dispatch",
        input="a shopper said something",
        expect=Expectation(agent=expected),
        synthetic=True,
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

    def test_it_reports_itself_unbuilt_rather_than_guessing(self) -> None:
        """A stub that picked an agent would produce a quotable accuracy figure.

        Derived from nothing, and somebody would quote it.
        """
        response = asyncio.run(build_target(None).run(_case("x", "care")))
        assert response.not_run
        assert response.dispatched_to is None
        assert "no dispatcher exists" in (response.error or "").lower()

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

    def test_dispatch_accuracy_is_not_gated_yet(self) -> None:
        """ADR-0031 requires a gate before the dispatcher ships, and a threshold

        set now would be drawn from cases written the same week, against a model
        nobody has measured on this workload. The gate comes from a baseline.
        """
        from neura_evals.metrics import THRESHOLDS

        assert "dispatch_accuracy" not in THRESHOLDS


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
