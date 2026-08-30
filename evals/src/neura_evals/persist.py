"""Writing a run to disk, so a failure can be read instead of reproduced.

**Open question E7, second half.** The first half was solved and is not this:
`AgentResponse` already carries the pre-verify ``draft`` and the ``verify_reason``,
and `report.py` prints both for failed cases. What it does not do is keep them.

That gap has now cost twice. On 2026-08-02 a check began failing and the harness
had recorded only ``composed chars=51``, which is what put the draft on the
response in the first place. On 2026-08-26 SELL's first eval run produced four
failures, they were printed in full, they were read — and by the time the one
that mattered needed a *second* reading, the terminal was gone and the only
surviving record was three fragments somebody had transcribed by hand into
`docs/open-questions.md`. The question A14 then could not answer was not "what
did the composer write", it was "what evidence was it written from" — a field
nobody thought to transcribe, because nobody knew yet which field would matter.

**That is the argument for writing the whole run rather than a nicer summary of
it.** A report is filtered by what the person printing it expected to need. A
suite run costs twenty minutes of local inference; the file it leaves behind
costs nothing and answers the question that has not been asked yet.

## What is written

Every case — passed and failed — with its checks, its draft, its verifier reason
and **the evidence the draft was written from**. Passed cases are included
deliberately: the failures are only interpretable against what a pass looked
like on the same run, and a file that holds only the failures makes "did this
regress" unanswerable without the other run too.

## What is not written

Nothing is redacted here, and that is a deliberate limit rather than an
oversight. These runs are golden datasets, and every case in every dataset is
marked ``synthetic: true`` — there is no real shopper and no real order in any
of them (**E1**, **B2**). **The day a real conversation enters a dataset, this
file starts writing real customer data to disk under an unversioned path, and
that is the moment this module needs a redaction pass and a retention rule.**
Recorded here rather than in a ticket, because the change that makes it true is
a change to a YAML file and will not look like it touches this code at all.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from neura_evals.runner import RunReport


def default_path(agent: str, *, directory: Path | None = None) -> Path:
    """``evals/reports/<agent>-<utc timestamp>.json``.

    Timestamped rather than overwritten: the whole use is comparing a run with
    the one before it, and Rule 4 asks for n≥3 either side of any prompt change.
    A path that overwrites turns six runs into one.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return (directory or Path("evals/reports")) / f"{agent}-{stamp}.json"


def write_report(report: RunReport, path: Path) -> Path:
    """Serialise the whole run. Returns the path actually written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_as_json(report), indent=2, default=_fallback), encoding="utf-8")
    return path


def _as_json(report: RunReport) -> dict[str, Any]:
    """The run as plain JSON.

    Built field by field rather than by dumping the dataclass, so that the two
    fields this file exists for cannot be lost to a refactor without a test
    noticing. `draft`, `verify_reason` and `evidence` are named here explicitly
    and are asserted on in `tests/unit`.
    """
    return {
        "target": report.target_name,
        "datasets": list(report.datasets),
        "judge": {
            "model": report.judge_model,
            "trust": _plain(report.judge_trust),
            "enabled": report.judge_enabled,
            "scores_are_trustworthy": report.scores_are_trustworthy,
        },
        # Carried into the file because a number read six weeks later without it
        # is a number somebody will quote as validation. `is_validation` is the
        # repository's own answer to "may this be repeated as fact" (E1).
        "is_validation": report.is_validation,
        "started_at": report.started_at.isoformat(),
        "duration_s": report.duration_s,
        "summary": {
            "total": report.summary.total,
            "passed": report.summary.passed,
            "synthetic": report.summary.synthetic,
            "unjudged": report.summary.unjudged,
            "unavailable": report.summary.unavailable,
            "pass_rate": report.summary.pass_rate,
            "metrics": dict(report.summary.metrics),
            # Beside every rate, how many cases produced it. Written because the
            # question this file exists to answer six weeks later — "was that
            # 1.00 real?" — is unanswerable from the rate alone.
            "coverage": {
                name: {"measured": measured, "cases_that_ran": scoreable}
                for name, (measured, scoreable) in report.summary.coverage.items()
            },
            # `expected -> chosen -> count` ([ADR-0031]). Kept rather than only
            # printed, for E7's reason: `dispatch_accuracy 0.85` six weeks later
            # cannot say whether the 15% went to an agent that answered or to one
            # that fetched a human, and that is the whole question.
            "dispatch_matrix": {
                expected: dict(chosen)
                for expected, chosen in report.summary.dispatch_matrix.items()
            },
            "gate_failures": [
                {"metric": name, "actual": actual, "threshold": threshold}
                for name, actual, threshold in report.summary.gate_failures()
            ],
            "p50_latency_ms": report.summary.p50_latency_ms,
            "p95_latency_ms": report.summary.p95_latency_ms,
            "total_cost_usd": str(report.summary.total_cost_usd),
        },
        "cases": [_case(result) for result in report.results],
    }


def _case(result: Any) -> dict[str, Any]:
    response = result.response
    return {
        "case_id": result.case_id,
        "intent": result.intent,
        "synthetic": result.synthetic,
        "passed": result.passed,
        "groundedness_score": result.groundedness_score,
        "checks": [
            {"name": c.name, "status": _plain(c.status), "detail": c.detail} for c in result.checks
        ],
        # The three fields E7 is about. `evidence` is the one the 2026-08-26
        # session needed and did not have: a draft is only judgeable against
        # what it was allowed to rely on, and "the fixture contains it" is not
        # the same claim as "this turn retrieved it".
        "draft": response.draft,
        "verify_reason": response.verify_reason,
        "escalation_reason": response.escalation_reason,
        "evidence": response.evidence,
        "reply": response.reply,
        "detected_intent": response.intent,
        # Which agent the dispatcher chose ([ADR-0031]), per case rather than
        # only in the aggregate matrix. E7 again: the matrix says *how many*
        # `care` messages went to `sell`, and reading a failure means knowing
        # **which** message did — a run file that recorded only the total would
        # answer the summary question and not the diagnostic one.
        "dispatched_to": response.dispatched_to,
        "tools_called": [
            {
                "name": t.name,
                "arguments": _plain(t.arguments),
                "authorised": t.authorised,
                "error": t.error,
            }
            for t in response.tools_called
        ],
        "escalated": response.escalated,
        "refused": response.refused,
        "blocked": response.blocked,
        "pii_leaked": response.pii_leaked,
        "structured_repairs": response.structured_repairs,
        "tokens_used": response.tokens_used,
        "llm_calls": response.llm_calls,
        "latency_ms": response.latency_ms,
        "cost_usd": str(response.cost_usd),
        # Kept apart from `error` for the E6 reason: a case the provider never
        # answered is not a case the agent got wrong, and a file that flattens
        # the two will be read as thirty-five failures one day.
        "infrastructure_error": response.infrastructure_error,
        "error": response.error,
        "not_run": response.not_run,
    }


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _fallback(value: Any) -> Any:
    """Last resort for anything the explicit mapping above did not flatten."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return str(value)


__all__ = ["default_path", "write_report"]
