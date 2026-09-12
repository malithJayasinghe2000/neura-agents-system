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
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from neura_core import get_logger

log = get_logger(__name__)

JUDGE_PROMPT_VERSION = "v1"

#: One logical judge call is **one** HTTP request attempt ([ADR-0038]).
#:
#: `openai==2.48.0` defaults `max_retries` to **2**, so an unset value means up
#: to three attempts per call — silently, with no record anywhere of how many
#: were actually made. That turns every quota estimate into a guess and makes a
#: slow failure unreadable: the Nemotron screen of 2026-09-12 spent 121s on its
#: first arm and nothing can now say whether that was one attempt or three.
#:
#: Retries are not *wrong*; an invisible retry is. A future retry mechanism is
#: explicit, bounded, separately budgeted, and reports its attempt count.
JUDGE_MAX_RETRIES = 0

#: A provider-supplied identifier is echoed only if it looks like one.
#:
#: A response id is diagnostic gold — it is what a provider's support asks for —
#: but it is a string from outside this process, and it lands in a report file.
#: Anything not matching is **dropped rather than truncated**: a prefix of an
#: unexpected string is still that string.
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class ProviderResponseShapeError(Exception):
    """A 2xx whose body carried no usable completion.

    **Never retried by the SDK**, because the SDK considers it a success:
    `_should_retry` is consulted only for non-2xx responses, and
    `_strict_response_validation` is `False` by default, so `construct_type`
    builds `ChatCompletion` with `model_construct` and a body of
    ``{"choices": null}`` becomes ``choices=None`` with no validation error.

    Subscripting that produced ``'NoneType' object is not subscriptable``, which
    names a Python operation rather than the thing that went wrong, and was
    persisted into the report as the judge's reasoning. The message this carries
    is **authored here** and contains no provider text.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        #: Authored text, safe to log and to persist.
        #:
        #: Read by :func:`_safe_error` **only after an isinstance check on this
        #: class**. The attribute name alone guarantees nothing — any exception
        #: from a gateway client could define one — so the type is the claim.
        self.safe_detail = detail


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
    latency_ms: int = Field(
        default=0,
        description=(
            "How long this one call took, **set on the failure path too**.\n\n"
            "A slow failure and a fast failure are different diagnoses — a 121s "
            "malformed response is a provider struggling, a 0.2s one is a provider "
            "refusing — and until 2026-09-12 neither was recorded anywhere."
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


def _safe_error(exc: Exception) -> str:
    """What went wrong, in fields that cannot have come from a prompt or a key.

    **`str(exc)` is never included**, and that is the whole function. An SDK
    exception for a 4xx can carry the response body, the request URL and the
    headers that were sent — and this string is logged *and* written into the
    report as the judge's reasoning, where ADR-0037 §7 has already established
    that a report is pasted into terminals and must not carry credentials.

    Four things are allowed through, each of which we either authored or can
    recognise: the exception type, an integer HTTP status, a provider id that
    matches :data:`_SAFE_ID`, and text this module wrote itself.
    """
    parts = [type(exc).__name__]

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        parts.append(f"HTTP {status}")

    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and _SAFE_ID.fullmatch(request_id):
        parts.append(f"request {request_id}")

    # **Our own type, checked with isinstance — never a duck-typed attribute.**
    # `getattr(exc, "safe_detail", ...)` would trust any exception that happens
    # to carry that name, and an SDK or a gateway client is free to define one
    # holding whatever it likes. The guarantee here is "this module authored
    # this string", and only the type can establish that.
    if isinstance(exc, ProviderResponseShapeError):
        parts.append(exc.safe_detail)

    return " · ".join(parts)


def _safe_response_id(response: Any) -> str:
    identifier = getattr(response, "id", None)
    return identifier if isinstance(identifier, str) and _SAFE_ID.fullmatch(identifier) else "?"


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
            # Explicit, and never the SDK default ([ADR-0038]). Left unset this
            # is 2, so `timeout_s` bounds an *attempt* and not a call, and the
            # number of requests a run spends against a quota is unknowable.
            max_retries=JUDGE_MAX_RETRIES,
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
        began = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            # Both shapes are real and only one of them was in the run that found
            # this: `choices: null` produced a NoneType error and `choices: []`
            # would have produced an IndexError. Neither names the fault, and the
            # SDK treats both as a success, so no retry and no exception fires.
            choices = getattr(response, "choices", None)
            if choices is None:
                raise ProviderResponseShapeError(
                    f"the provider returned a success with no choices field "
                    f"(response {_safe_response_id(response)})"
                )
            if not choices:
                raise ProviderResponseShapeError(
                    f"the provider returned a success with an empty choices list "
                    f"(response {_safe_response_id(response)})"
                )
            content = choices[0].message.content or "{}"
            verdict = Verdict.model_validate(_extract_json(content))
            return verdict.model_copy(update={"latency_ms": _elapsed_ms(began)})
        except Exception as exc:
            # Neither a pass nor a fail. Scoring an outage as a pass turns it into
            # a green build; scoring it as a failure — which this did until a
            # rate-limited free tier ran out mid-run — reports a hallucination
            # that never happened. Both are wrong in the same way: they state a
            # measurement that was not made.
            #
            # A timeout, a 429, a connection failure, a 5xx and a malformed 2xx
            # all land here and all mean the same thing: no judgement was
            # returned ([ADR-0038]). None of them is the judge's opinion.
            detail = _safe_error(exc)
            log.error("judge_call_failed", model=self._config.model, error=detail)
            return Verdict(
                passed=False,
                score=0.0,
                reasoning=f"judge unavailable: {detail}",
                unsupported_claims=[],
                available=False,
                latency_ms=_elapsed_ms(began),
            )


def _elapsed_ms(began: float) -> int:
    return int((time.perf_counter() - began) * 1000)


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
