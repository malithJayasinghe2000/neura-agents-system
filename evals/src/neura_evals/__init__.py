"""neura-evals — the agent evaluation harness.

Built BEFORE the agent, deliberately (docs/roadmap.md milestone 1.4 precedes
1.10). Three reasons:

1. Development runs on local models and production on a cloud API. Without a
   scoring suite, that swap is a leap of faith.
2. A prompt edit is a behaviour change. Only an eval catches a one-word change
   that breaks refusal behaviour.
3. No number goes on the website that this suite or a live pilot did not produce.

Two properties the reports never let you forget: whether the judge was strong
enough to be believed, and whether the cases were real or invented.
"""

from neura_evals.dataset import (
    ADVERSARIAL,
    Dataset,
    EvalCase,
    FixtureMode,
    Intent,
    load_all,
    load_dataset,
)
from neura_evals.judge import Judge, JudgeConfig, JudgeTrust, Verdict
from neura_evals.metrics import THRESHOLDS, CaseResult, RunSummary, score_case, summarise
from neura_evals.runner import RunReport, compare, run_eval
from neura_evals.target import AgentResponse, EvalTarget, ToolInvocation

__all__ = [
    "ADVERSARIAL",
    "THRESHOLDS",
    "AgentResponse",
    "CaseResult",
    "Dataset",
    "EvalCase",
    "EvalTarget",
    "FixtureMode",
    "Intent",
    "Judge",
    "JudgeConfig",
    "JudgeTrust",
    "RunReport",
    "RunSummary",
    "ToolInvocation",
    "Verdict",
    "compare",
    "load_all",
    "load_dataset",
    "run_eval",
    "score_case",
    "summarise",
]
