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
from urllib.parse import urlsplit

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
    """The judge is the same model being evaluated — marking its own homework.

    **Declared in milestone 1.4 and unreachable until 2026-09-12** ([ADR-0037]).
    Nothing set it, and `judge_from_env()` decided trust from the model *name*
    alone, so `cloud-prod` — where `.env` puts `gemini-3.6-flash` on every chat
    role *and* on the judge — reported `trusted` while the model graded its own
    answer (open question E11). :func:`neura_evals.config.resolve_judge_trust`
    now reaches it.

    It outranks :attr:`UNTRUSTED_WEAK_MODEL`: a small model grading itself is
    both, and self-judging is the more specific fact about why the number
    cannot be believed.
    """

    UNTRUSTED_UNVERIFIED = "untrusted:unverified"
    """**Whether the judge grades its own answer could not be determined.**

    The role map under test could not be inspected — an unknown map name, a
    provider that could not be built, or `model_for()` failing for a reason that
    is not `RoleNotConfiguredError`. The judge may well be independent; nobody
    knows, and *"nobody knows"* is not *"yes"*.

    Distinct from the other two because the fix is different: this one is a
    defect or a misconfiguration to go and find, not a judge to replace. It is
    non-qualifying for the same reason they are ([ADR-0037] §1).
    """


class Verdict(BaseModel):
    """One judgement — or the absence of one."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str
    unsupported_claims: list[str] = Field(default_factory=list)
    available: bool = Field(
        default=True,
        description=(
            "False when the judge could not be reached at all. **Neither a pass nor a "
            "fail** — the case is unjudged, and it is excluded from the groundedness "
            "metric rather than counted against the agent.\n\n"
            "The distinction is not pedantic. A rate-limited judge scored as a failure "
            "reports that the agent hallucinated, which is a false accusation that "
            "looks exactly like a real regression — and the natural response to it is "
            "to go looking for a bug in the agent that is not there."
        ),
    )


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


def sanitise_endpoint(url: str) -> str:
    """The **origin** of an endpoint — scheme, host and valid port, nothing else.

    A report is written to disk and pasted into terminals, so everything that
    can carry a credential is removed:

    * **user information** — `https://user:secret@host/` is a legal base URL;
    * **query string** — plenty of gateways accept `?key=…`;
    * **fragment** — the same, and it survives copy-paste;
    * **the path** — and this one is not obvious. A generic gateway may route by
      a secret in a path segment (`/v1/sk-live-…/openai`), so a path is not safe
      merely because it usually is. The diagnostic value of *"which product"* is
      not worth the class of leak, and the host already answers *"which vendor"*.

    **Never raises.** `urlsplit` defers port validation to attribute access, so
    `https://host:notaport/v1` raises `ValueError` on `.port` — outside the
    original `try` in the first version of this function, which made a sanitiser
    a source of crashes. Anything malformed degrades to the empty string rather
    than to the raw value: the failure has to be safe in the direction of saying
    less.

    IPv6 literals keep their brackets, which `hostname` strips.
    """
    try:
        parsed = urlsplit(url.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return ""

    if not host or not parsed.scheme:
        return ""
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}:{port}" if port else f"{parsed.scheme}://{host}"


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

    @property
    def endpoint(self) -> str:
        """The base URL reduced to its origin — no credentials anywhere in it."""
        return sanitise_endpoint(self.base_url)


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

    @property
    def endpoint(self) -> str:
        """Where this judge lives, **sanitised**. The raw base URL never leaves here."""
        return self._config.endpoint

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
            # Neither a pass nor a fail. Scoring an outage as a pass turns it into
            # a green build; scoring it as a failure — which this did until a
            # rate-limited free tier ran out mid-run — reports a hallucination
            # that never happened. Both are wrong in the same way: they state a
            # measurement that was not made.
            log.error("judge_call_failed", model=self._config.model, error=str(exc))
            return Verdict(
                passed=False,
                score=0.0,
                reasoning=f"judge unavailable: {exc}",
                unsupported_claims=[],
                available=False,
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
