"""Judge configuration, resolved from the environment.

Deliberately explicit about **trust**: an eval run using a weak judge still
produces numbers, and those numbers must be visibly untrustworthy rather than
quietly wrong. Every report carries the judge's trust level.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, replace

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


# ── Self-judging: is the judge one of the models under test? ─────────────────
#
# Open question E11, [ADR-0037]. `judge_from_env()` decides trust from the model
# name and has no idea what the agent is running on, so on `cloud-prod` — where
# `.env` puts `gemini-3.6-flash` on every chat role **and** on the judge — a run
# would grade the model's own answer and label the score `trusted`.

#: The one routing suffix stripped before comparing two model names.
#:
#: `openrouter/x:free` and `openrouter/x` are the same weights on the same route
#: with different billing, so a judge on the free tier of the model under test is
#: still marking its own homework. **Nothing else is stripped**, and that is the
#: line: a *tier* suffix names the same route, a *vendor prefix* names a
#: different one, and deciding that `google/gemini-x` is `gemini-x` would be
#: guessing that two gateways mean the same thing by the same bare name.
_TIER_SUFFIX = ":free"


def normalise_model(name: str) -> str:
    """A model name reduced to what identity comparison should see.

    Whitespace, case and the recognised tier suffix — nothing more. Deliberately
    **not** a fuzzy matcher: `gemini-3.6-flash` and `gemini-3.5-flash` are
    different models and a rule that merged them would silently disqualify a
    legitimate judge.
    """
    cleaned = name.strip().casefold()
    return cleaned.removesuffix(_TIER_SUFFIX) if cleaned.endswith(_TIER_SUFFIX) else cleaned


def is_self_judging(judge_model: str, agent_models: Iterable[str]) -> bool:
    """Does the judge share a model with any role in the run under test?

    **Endpoint-independent, and that is the point.** The same weights reached
    through two gateways self-judge identically, so requiring the base URLs to
    match as well would miss the most plausible way to configure it by accident.

    Compared against **every** configured role rather than only the two that
    touch the graded text (`REASONER` writes the reply, `GUARD` has already
    ruled it grounded). Fail-closed: the two that matter are always included,
    and a map that shares a model between roles is the ordinary case here.
    """
    judge = normalise_model(judge_model)
    if not judge:
        return False
    return any(normalise_model(model) == judge for model in agent_models if model.strip())


@dataclass(frozen=True, slots=True)
class RoleMapModels:
    """Which models a run uses — **and whether we actually managed to find out**.

    The distinction is the whole of [ADR-0037] §1. An empty set has two possible
    meanings that must never be confused:

    * ``inspected=True, models=frozenset()`` — nothing ran (`--no-agent`, or an
      injected target). Nothing was self-judged, so a judge stays trusted.
    * ``inspected=False`` — the role map could not be read. The judge may be
      independent; **nobody knows**, and the first version of this code answered
      that question with "trusted" by handing an empty set to the comparison.
    """

    models: frozenset[str] = frozenset()
    #: False when inspection failed. Never trust a judge against an uninspected map.
    inspected: bool = True
    #: Why inspection failed, for the reader who has to go and fix it.
    detail: str = ""

    @property
    def described(self) -> str:
        return ", ".join(sorted(self.models)) or "(none)"


def resolve_judge_trust(config: JudgeConfig, agent_models: RoleMapModels) -> JudgeConfig:
    """Downgrade a judge that is grading itself, or that we could not check.

    Applied **after** `judge_from_env()`, because only the caller knows which
    role map is being run. It only ever *subtracts* confidence.

    Three outcomes, and the middle one exists because its absence was a
    fail-open edge: an inspection that blew up looked exactly like a run with no
    models in it, and a run with no models in it is legitimately trusted.

    ============================  ===========================================
    ``inspected=False``           ``UNTRUSTED_UNVERIFIED`` — we did not check
    judge matches a role          ``UNTRUSTED_SELF_JUDGING``
    otherwise                     unchanged
    ============================  ===========================================

    Self-judging outranks a weak-model label: both are true of a small model
    grading itself, and this one says why the number cannot be believed.
    """
    if not agent_models.inspected:
        log.error(
            "judge_qualification_unknown",
            model=config.model,
            detail=agent_models.detail
            or "the role map under test could not be inspected; self-judging was not ruled out",
        )
        return replace(config, trust=JudgeTrust.UNTRUSTED_UNVERIFIED)

    if not is_self_judging(config.model, agent_models.models):
        return config

    log.warning(
        "judge_is_self_judging",
        model=config.model,
        detail=(
            "the judge is one of the models under test; groundedness from this run "
            "is not evidence and cannot satisfy a required metric"
        ),
    )
    return replace(config, trust=JudgeTrust.UNTRUSTED_SELF_JUDGING)
