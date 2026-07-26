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
_WEAK_MODEL_MARKERS = ("llama3.2", ":1b", ":3b", "phi3", "gemma:2b", "qwen2.5:0", "tinyllama")


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
