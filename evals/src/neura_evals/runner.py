"""Running an eval and reporting it."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from neura_core import get_logger
from neura_evals.dataset import Dataset, EvalCase
from neura_evals.judge import Judge, JudgeTrust
from neura_evals.metrics import CaseResult, RunSummary, score_case, summarise
from neura_evals.target import AgentResponse, EvalTarget

log = get_logger(__name__)

# Free judge tiers rate-limit aggressively, so concurrency stays low by default.
DEFAULT_CONCURRENCY = 4


@dataclass(slots=True)
class RunReport:
    target_name: str
    datasets: list[str]
    judge_model: str
    judge_trust: JudgeTrust | None
    started_at: datetime
    duration_s: float
    #: Where the judge lives, **already sanitised** by `Judge.endpoint` — no user
    #: information, no query string, no fragment. Recorded because "which judge
    #: produced this number" is unanswerable six weeks later from the model name
    #: alone, and defaulted because a run with no judge has no endpoint.
    judge_endpoint: str = ""
    results: list[CaseResult] = field(default_factory=list)
    summary: RunSummary = field(default_factory=RunSummary)

    @property
    def judge_enabled(self) -> bool:
        """``--no-judge`` skips judged metrics entirely — different from a weak judge."""
        return self.judge_trust is not None

    @property
    def scores_are_trustworthy(self) -> bool:
        """Judged metrics from an untrusted judge are not measurements.

        With no judge at all there are no judged metrics, so the mechanical
        checks that did run stand on their own.
        """
        return self.judge_trust is None or self.judge_trust is JudgeTrust.TRUSTED

    @property
    def is_validation(self) -> bool:
        """A run over synthetic cases proves the harness works, not the agent."""
        return self.summary.synthetic < self.summary.total


async def run_eval(
    *,
    target: EvalTarget,
    datasets: list[Dataset],
    judge: Judge | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> RunReport:
    started = datetime.now(UTC)
    clock = time.perf_counter()

    cases: list[EvalCase] = [case for dataset in datasets for case in dataset.cases]
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(case: EvalCase) -> CaseResult:
        async with semaphore:
            began = time.perf_counter()
            try:
                response = await target.run(case)
            except Exception as exc:
                log.error("case_execution_failed", case_id=case.id, error=str(exc))
                response = AgentResponse(reply="", error=f"target raised: {exc}")
            if not response.latency_ms:
                response.latency_ms = int((time.perf_counter() - began) * 1000)
            return await score_case(case, response, judge)

    results = await asyncio.gather(*(run_one(c) for c in cases))

    return RunReport(
        target_name=target.name,
        datasets=[d.name for d in datasets],
        judge_model=judge.model if judge else "none",
        judge_trust=judge.trust if judge else None,
        judge_endpoint=judge.endpoint if judge else "",
        started_at=started,
        duration_s=round(time.perf_counter() - clock, 2),
        results=list(results),
        # The judge's trust reaches the summary here and nowhere else, so a
        # judged metric is marked untrusted at the moment it is aggregated
        # rather than by a caller remembering to ([ADR-0037]).
        summary=summarise(list(results), judge_trust=judge.trust if judge else None),
    )


#: The process exited without complaint.
EXIT_OK = 0
#: **About the agent.** A required metric was missing, or a gate was not met.
EXIT_GATE = 1
#: **About the infrastructure.** At least one case never reached the model, so
#: the run is not a measurement whatever its numbers say.
#:
#: Three rather than two: argparse exits 2 on a usage error, and a CI job that
#: could not tell "you typed the flag wrong" from "the model server is down"
#: would retry the first for ever and page nobody for the second.
EXIT_UNMEASURED = 3


@dataclass(frozen=True, slots=True)
class RunVerdict:
    """Did this run pass, and what does the process exit with?

    **Separated from the report on purpose.** A `RunReport` is what was measured;
    a verdict is what was *required*, and the requirement comes from the command
    line because it depends on which datasets the run was pointed at. CARE's
    suite must produce `injection_resistance`; the dispatch suite cannot, and
    must produce `expensive_misroute_rate` instead. A single answer baked into
    this module would be wrong for one of them (open question E9).
    """

    required: tuple[str, ...] = ()
    #: Required metrics the run never emitted. Finding 27's actual failure.
    missing_required: tuple[str, ...] = ()
    #: Required metrics that **exist and may not be believed** — the judge was
    #: weak, or was one of the models under test ([ADR-0037], open question E11).
    #:
    #: A third way to fail a requirement, beside absent and breached. Without it
    #: a self-judged `groundedness 0.98` satisfies `--require groundedness`, which
    #: is [ADR-0036]'s false green wearing a number instead of a gap.
    untrusted_required: tuple[str, ...] = ()
    #: ``(metric, actual, threshold)`` for required metrics whose gate was not met.
    required_breached: tuple[tuple[str, float, float], ...] = ()
    #: Every gate breach, required or not. Reported always; blocking only under
    #: ``--fail-on-gate``.
    gate_failures: tuple[tuple[str, float, float], ...] = ()
    #: Cases that never reached the model. Blocking under ``--fail-on-unmeasured``.
    errored: int = 0
    fail_on_gate: bool = False
    fail_on_unmeasured: bool = False

    @property
    def reasons(self) -> list[str]:
        """Why this run failed, in the order the exit code is decided."""
        out: list[str] = []
        if self.fail_on_unmeasured and self.errored:
            out.append(
                f"{self.errored} case(s) never reached the model. "
                "Nothing here is a measurement — fix the provider and re-run."
            )
        for name in self.missing_required:
            out.append(
                f"required metric {name.replace('_', ' ')!r} was never measured. "
                "A gate cannot be met by a number that does not exist."
            )
        for name in self.untrusted_required:
            out.append(
                f"required metric {name.replace('_', ' ')!r} was measured by a judge that "
                "cannot be believed, so it satisfies nothing. Configure a judge that is not "
                "one of the models under test."
            )
        for name, actual, threshold in self.required_breached:
            out.append(
                f"required gate {name.replace('_', ' ')} {actual:.2f} (gate {threshold:.2f})"
            )
        if self.fail_on_gate:
            required = {n for n, _, _ in self.required_breached}
            out += [
                f"gate {name.replace('_', ' ')} {actual:.2f} (gate {threshold:.2f})"
                for name, actual, threshold in self.gate_failures
                if name not in required
            ]
        return out

    @property
    def exit_code(self) -> int:
        """Infrastructure first, and that ordering is the decision.

        A run that could not reach the model has numbers that mean nothing, so
        reporting *"injection resistance missing"* as the headline would send
        somebody looking at the datasets. The provider is the thing to fix, and
        the exit code says so.
        """
        if self.fail_on_unmeasured and self.errored:
            return EXIT_UNMEASURED
        if self.missing_required or self.untrusted_required or self.required_breached:
            return EXIT_GATE
        if self.fail_on_gate and self.gate_failures:
            return EXIT_GATE
        return EXIT_OK

    @property
    def ok(self) -> bool:
        return self.exit_code == EXIT_OK


def judge_run(
    report: RunReport,
    *,
    required: Sequence[str] = (),
    fail_on_gate: bool = False,
    fail_on_unmeasured: bool = False,
) -> RunVerdict:
    """Turn a report plus what was asked of it into a pass or a fail."""
    gate_failures = tuple(report.summary.gate_failures())
    required = tuple(required)
    missing = tuple(report.summary.missing_required(required))
    untrusted = tuple(n for n in required if n in report.summary.untrusted_metrics)
    return RunVerdict(
        required=required,
        missing_required=missing,
        untrusted_required=untrusted,
        required_breached=tuple(f for f in gate_failures if f[0] in set(required)),
        gate_failures=gate_failures,
        errored=report.summary.errored,
        fail_on_gate=fail_on_gate,
        fail_on_unmeasured=fail_on_unmeasured,
    )


def compare(baseline: RunReport, candidate: RunReport) -> list[tuple[str, float, float, float]]:
    """(metric, baseline, candidate, delta) for every shared metric.

    This is what turns a model swap into a decision rather than a leap of faith
    (docs/architecture/llm-abstraction.md §8).
    """
    shared = sorted(set(baseline.summary.metrics) & set(candidate.summary.metrics))
    return [
        (
            name,
            baseline.summary.metrics[name],
            candidate.summary.metrics[name],
            candidate.summary.metrics[name] - baseline.summary.metrics[name],
        )
        for name in shared
    ]


def dataset_dirs() -> list[Path]:
    """Every installed agent's dataset directory.

    Datasets moved *into* the agents in milestone 1.11. They are a statement
    about one agent's behaviour, so they version and review with the code that
    produces it — and this package must not know which agents exist, which rules
    out a path constant here (AGENTS.md, "Add an agent").
    """
    from neura_evals.discovery import discover_agents

    return [agent.dataset_dir for agent in discover_agents()]
