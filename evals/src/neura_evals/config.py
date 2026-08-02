"""Judge configuration, resolved from the environment.

Deliberately explicit about **trust**: an eval run using a weak judge still
produces numbers, and those numbers must be visibly untrustworthy rather than
quietly wrong. Every report carries the judge's trust level.
"""

from __future__ import annotations

import os

from neura_core import get_logger
from neura_evals.judge import JudgeConfig, JudgeTrust

log = get_logger(__name__)

# Small local models cannot reliably judge; listed so the harness can label its
# own output honestly rather than implying a measurement it did not make.
#: Names that mean "this model is too small to grade another model's work".
#:
#: The first seven are Ollama-style tags and were all this list knew until
#: 2026-08-02, when the judge moved to a cloud gateway and the gap showed: a
#: hosted 9B is called `nvidia/nemotron-nano-9b-v2:free`, matches none of the
#: Ollama markers, and would have been labelled **trusted**. That is the
#: house failure mode — a number that looks like a measurement and is not — in
#: the one place whose entire job is to refuse it.
#:
#: **Every marker here is delimited, and that is not fussiness.** The first draft
#: used bare `"mini"`, which matches `ge-mini-2.5-flash` and quietly declared a
#: perfectly good judge untrustworthy. Caught by the existing
#: `test_configured_strong_model_is_trusted`. Size suffixes carry a leading
#: hyphen or colon for the same reason: `-9b` must not match the `a12b` or `120b`
#: of a much larger mixture-of-experts model.
_WEAK_MODEL_MARKERS = (
    "llama3.2",
    "phi3",
    "gemma:2b",
    "qwen2.5:0",
    "tinyllama",
    ":1b",
    ":2b",
    ":3b",
    ":4b",
    "-1b",
    "-2b",
    "-3b",
    "-4b",
    "-7b",
    "-8b",
    "-9b",
    "-nano",
    "/nano",
    "-mini",
    "/mini",
    "-tiny",
    "/tiny",
)


def _looks_weak(model: str) -> bool:
    lowered = model.lower()
    return any(marker in lowered for marker in _WEAK_MODEL_MARKERS)


def judge_from_env() -> JudgeConfig:
    """Build the judge from environment variables.

    Preferred (trusted):
        EVAL_JUDGE_BASE_URL, EVAL_JUDGE_API_KEY, EVAL_JUDGE_MODEL

    Fallback (untrusted): local Ollama. The harness still runs end to end with no
    budget and no API key — every score is simply labelled untrusted.
    """
    base_url = os.getenv("EVAL_JUDGE_BASE_URL")
    api_key = os.getenv("EVAL_JUDGE_API_KEY")
    model = os.getenv("EVAL_JUDGE_MODEL")

    if base_url and api_key and model:
        trust = JudgeTrust.UNTRUSTED_WEAK_MODEL if _looks_weak(model) else JudgeTrust.TRUSTED
        if trust is not JudgeTrust.TRUSTED:
            log.warning("judge_is_weak", model=model)
        return JudgeConfig(base_url=base_url, api_key=api_key, model=model, trust=trust)

    fallback_model = os.getenv("OLLAMA_JUDGE_MODEL", "qwen3.5:9b")
    log.warning(
        "judge_not_configured",
        detail="EVAL_JUDGE_* not set; falling back to local Ollama. Scores are UNTRUSTED.",
        model=fallback_model,
    )
    return JudgeConfig(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        model=fallback_model,
        trust=JudgeTrust.UNTRUSTED_WEAK_MODEL,
    )
