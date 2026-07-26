"""Running an eval and reporting it."""

from __future__ import annotations

import asyncio
import time
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
        started_at=started,
        duration_s=round(time.perf_counter() - clock, 2),
        results=list(results),
        summary=summarise(list(results)),
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


def dataset_dir() -> Path:
    """``evals/datasets`` — this file is at ``evals/src/neura_evals/runner.py``."""
    return Path(__file__).resolve().parents[2] / "datasets"
