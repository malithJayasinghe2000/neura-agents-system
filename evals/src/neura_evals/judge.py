"""The LLM judge — an AI scoring the AI's answers.

Some qualities cannot be checked with string matching. "Is every factual claim
in this reply actually supported by the data the agent retrieved?" needs
judgement, so a model provides it.

**The judge is itself fallible**, so three controls apply
(docs/architecture/evaluation-strategy.md §3.1):

1. The judge is **always a strong model** — never the same small local model
   being evaluated. A weak model grading a weak model produces scores that look
   like measurements and are not. This is the one place worth spending money.
2. Judge prompts are versioned like any other prompt.
3. A sample of judgements is human-verified, and judge-vs-human agreement is
   tracked as its own metric. A judge that drifts from human agreement is retired.

Any OpenAI-compatible endpoint works — Gemini, Ollama, or another cloud
provider — because that is the one interface the whole system speaks. Swapping
judge is a config change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from neura_core import get_logger

log = get_logger(__name__)

JUDGE_PROMPT_VERSION = "v1"


class JudgeTrust(StrEnum):
    """How much a judge's scores can be believed.

    Surfaced on every report. A number produced by an untrusted judge must never
    be quoted as a measurement.
    """

    TRUSTED = "trusted"
    """A strong model, distinct from the model under test."""

    UNTRUSTED_WEAK_MODEL = "untrusted:weak-model"
    """A small local model. Scores are directional at best."""

    UNTRUSTED_SELF_JUDGING = "untrusted:self-judging"
    """The judge is the same model being evaluated — marking its own homework."""


class Verdict(BaseModel):
    """One judgement."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str
    unsupported_claims: list[str] = Field(default_factory=list)


GROUNDEDNESS_PROMPT = """\
You are evaluating whether a customer-support reply is GROUNDED.

Grounded means: every factual claim in the reply is supported by the evidence
provided. Order numbers, dates, prices, stock levels, tracking numbers and
policy terms must all appear in the evidence.

A reply that says "I don't have that information" or hands off to a human is
GROUNDED — declining is never an unsupported claim.

Generic pleasantries ("thanks for reaching out") are not factual claims.

EVIDENCE AVAILABLE TO THE AGENT:
{evidence}

THE AGENT'S REPLY:
{reply}

Respond with JSON only:
{{
  "passed": true or false,
  "score": 0.0 to 1.0,
  "reasoning": "one sentence",
  "unsupported_claims": ["each claim not backed by the evidence"]
}}"""


RELEVANCE_PROMPT = """\
You are evaluating whether a customer-support reply ADDRESSES the question.

A reply that correctly declines or escalates DOES address the question — it is a
valid outcome, not a failure.

CUSTOMER ASKED:
{question}

THE AGENT REPLIED:
{reply}

Respond with JSON only:
{{
  "passed": true or false,
  "score": 0.0 to 1.0,
  "reasoning": "one sentence",
  "unsupported_claims": []
}}"""


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    """Where the judge lives. Any OpenAI-compatible endpoint."""

    base_url: str
    api_key: str
    model: str
    trust: JudgeTrust = JudgeTrust.TRUSTED
    timeout_s: float = 60.0

    @property
    def is_trusted(self) -> bool:
        return self.trust is JudgeTrust.TRUSTED


class Judge:
    """Scores replies that cannot be checked mechanically."""

    def __init__(self, config: JudgeConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout_s,
        )

    @property
    def trust(self) -> JudgeTrust:
        return self._config.trust

    @property
    def model(self) -> str:
        return self._config.model

    async def grounded(self, *, reply: str, evidence: str) -> Verdict:
        """Is every factual claim supported? The metric that protects the customer."""
        return await self._ask(
            GROUNDEDNESS_PROMPT.format(evidence=evidence or "(no evidence retrieved)", reply=reply)
        )

    async def relevant(self, *, question: str, reply: str) -> Verdict:
        return await self._ask(RELEVANCE_PROMPT.format(question=question, reply=reply))

    async def _ask(self, prompt: str) -> Verdict:
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            return Verdict.model_validate(_extract_json(content))
        except Exception as exc:
            # A judge failure must not be silently scored as a pass — that would
            # turn an outage into a green build.
            log.error("judge_call_failed", model=self._config.model, error=str(exc))
            return Verdict(
                passed=False,
                score=0.0,
                reasoning=f"judge unavailable: {exc}",
                unsupported_claims=[],
            )


def _extract_json(content: str) -> dict[str, Any]:
    """Parse JSON, tolerating models that wrap it in prose or a code fence."""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        content = content.removeprefix("json").strip()
    try:
        return dict(json.loads(content))
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return dict(json.loads(content[start : end + 1]))
        raise
