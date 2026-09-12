# ADR-0038 — Judge Calls Do Not Retry Invisibly, And One Arm's Outage Is Not The Other Arm's Verdict

**Status:** **Accepted** — owner decision, 2026-09-12 · **Date:** 2026-09-12 · **Builds on:** [ADR-0037](0037-a-model-may-not-grade-its-own-answer.md) §6, [ADR-0036](0036-a-run-that-measured-nothing-fails.md) §1 · **Supersedes nothing. ADR-0037 is unchanged and remains accepted.**

## Context

Found on 2026-09-12 by the first live execution of `--check-judge` against a candidate independent judge — the Step 1 functioning screen for the judge selection ADR-0037 deliberately left unmade. The screen failed, and it failed in three separable ways, only one of which was about the judge.

```
  ✘ the judge could not be reached at all
    judge unavailable: 'NoneType' object is not subscriptable

  ✘ accepts a grounded reply    score=0.0
  ✘ rejects a hallucination     score=0.0
        caught: 'order arrived yesterday'
        caught: 'neighbour signed for it'
```

**Read the last three lines together.** The screen printed a red cross against *"rejects a hallucination"* and then, immediately beneath it, the two fabricated claims the judge had correctly caught. The second call worked. It returned `passed=False`, `score=0.0` and both unsupported claims — a textbook correct refusal — and the report said it failed.

### Three defects, and the middle one is the new shape

**1. The arms were ANDed.** `reachable = grounded.available and hallucinated.available`, and both ticks were gated on it. The intent was sound and is ADR-0037's: an unreachable judge returns `passed=False`, which satisfies *"rejects a hallucination"* perfectly, so a dead judge must never print a green tick. The implementation made one arm's infrastructure failure rewrite the other arm's correct result.

**This is the house failure mode arriving from the opposite side.** Finding 12, Finding 23, the 2026-08-27 `tool_selection_accuracy` vacuum and Finding 27 are all *a check that stopped checking, and said green*. This is a check that checked, got the right answer, and said red over the top of it. A reader who trusts the glyph learns the judge cannot catch a fabrication. A reader who reads two lines further learns it can. **Both colours lie when the outcome has three states and the display has two.**

**2. `'NoneType' object is not subscriptable` was the published diagnosis.** The body returned a `2xx` whose `choices` was `null`. `openai==2.48.0` defaults `_strict_response_validation` to `False`, so a response is built by `construct_type` — Pydantic's `model_construct`, no validation — and `ChatCompletion.choices`, declared `List[Choice]` and required, arrives as `None` without complaint. `response.choices[0]` then raises, the blanket `except Exception` catches it, and `f"judge unavailable: {exc}"` names a Python operation rather than the fault. `choices: []` would have produced an `IndexError` and been no better.

That string is not only printed. It goes into `Verdict.reasoning`, which `score_case` puts into a `Check` detail, which `--out` writes to disk. **The generic `str(exc)` path is the same hazard ADR-0037 §7 closed for endpoints, still open one field away**: an SDK exception for a 4xx can carry the response body, the request URL and the headers that were sent.

**3. The number of HTTP requests the screen spent is unknowable.** `Judge.__init__` passed `base_url`, `api_key` and `timeout` and left `max_retries` unset. The SDK default is **2** (`_constants.py: DEFAULT_MAX_RETRIES = 2`), and the retry loop is `for retries_taken in range(max_retries + 1)` — **up to three attempts per logical call**, on timeouts, on connection failures, and on `408`, `409`, `429` and `5xx`.

So `timeout_s=60.0` bounded an *attempt*, not a call. The two arms took ~121s and ~76s, both over the timeout. **It cannot be determined how many requests reached the provider**, and inference does not close the gap: httpx timeouts bound a single operation rather than total elapsed time, so a slow single attempt and a retried pair produce the same wall clock. A session estimating quota consumption for this project's 50-requests-per-day free tier was working from a number nothing measures.

The malformed response itself was **not** retried — `_should_retry` is consulted only for non-2xx, and the SDK treated a body with no completion in it as a success.

## Decision

> **One logical judge call is at most one SDK request attempt. A timeout, a 429, a connection failure, a 5xx and a malformed success are all `available=False` and none of them is a verdict. Each arm of the screen is graded from its own verdict, and no arm changes the display of another.**

### 1. `max_retries=0`, passed explicitly

`JUDGE_MAX_RETRIES = 0`, named as a constant and passed to `AsyncOpenAI` in `Judge.__init__`. A test asserts the constructor argument, so a future SDK default change cannot silently restore retries.

**Retries are not wrong; an invisible retry is.** What is rejected here is inheriting a retry policy nobody chose, from a library default, into every cost, quota and latency figure the project produces.

**No application-level retry is added in this change.** A qualification probe that retries cannot measure request consumption or latency, which is the entire purpose of running it.

**Any future retry mechanism is explicit, bounded, separately budgeted, and reports its attempt count and latency.** It is a different decision with a different justification and it gets its own ADR. One interaction must be stated in advance: a retry layer makes a transient `429` invisible — the second attempt succeeds and `ProviderRateLimitedError` never surfaces — which weakens [ADR-0036 §6](0036-a-run-that-measured-nothing-fails.md), where a rate limit was deliberately classified as a provider failure so that a quota running out could not be mistaken for a defence working.

### 2. Three arm outcomes, and the exit code still demands two passes

| outcome | meaning |
|:--|:--|
| `PASSED` | the judge answered, and answered correctly |
| `FAILED` | the judge answered, and was wrong — **the only outcome about the judge** |
| `ERRORED` | no usable judgement: timeout, 429, connection failure, 5xx, malformed 2xx |

The same argument as ADR-0036 §1's four case outcomes, one level down: an arm that never got an answer is neither a pass nor a fail.

Exit **0** only when both arms are `PASSED`. `ERRORED` is not a pass, so a dead judge still fails the command — what changes is that it no longer drags a working arm down with it. An errored screen says *"could not be screened — N of 2 arms returned no judgement"* rather than *"not behaving correctly"*, because the second is a statement about the judge's opinions and no opinion was obtained.

**An errored arm prints no score.** `score=0.0` on an unreachable judge is a default and reads as a measurement.

### 3. A malformed success is named as what it is

`choices is None` and `choices == []` are both checked explicitly and raise `ProviderResponseShapeError`, whose message is **authored in this module** and carries a provider response id only when it matches `[A-Za-z0-9_.:-]{1,64}`. An id that does not match is **dropped rather than truncated**: a prefix of an unexpected string is still that string.

### 4. What may appear in a persisted diagnostic

`_safe_error()` is an allowlist, and `str(exc)` is never part of it:

| allowed | why |
|:--|:--|
| exception type name | ours to read, no external content |
| integer HTTP status | a number |
| provider id matching `_SAFE_ID` | what a provider's support asks for |
| text authored in `judge.py` | safe by construction — **established by `isinstance(exc, ProviderResponseShapeError)`, never by the presence of a `safe_detail` attribute.** An attribute name is not a provenance claim: any exception from an SDK or a gateway client is free to define one, and trusting it would reopen the hole from the other end |

Never: raw exception text, response bodies, headers, request URLs, prompts, keys or credentials. An exception carrying no recognised field yields its type name alone — **less, rather than something unexamined**, which is ADR-0037 §7's rule applied to the field next door.

### 5. Per-arm latency, on the failure path too

`Verdict.latency_ms`, set in both branches of `_ask` and printed per arm. A 121s malformed response is a provider struggling; a 0.2s one is a provider refusing. Neither was recorded anywhere.

### 6. "At most", and never a claim about what the provider received

The screen prints `2 logical judge calls · at most 2 SDK request attempts (max_retries=0)`. **"At most" is load-bearing.** A call that fails before its request leaves this process made no attempt at all, and a report that says the provider received two requests when it may have received one is the same class of error as the number this ADR exists to stop guessing.

Logical calls and HTTP attempts are never presented as one number.

## Consequences

**Good.** The screen can no longer print a failure over a correct answer. A malformed provider response is diagnosable from the report instead of requiring the reader to know that `choices[0]` is a subscript. Request consumption is now a fact rather than a range, which is what the judge-qualification procedure needs in order to be budgeted at all. The `str(exc)` disclosure path into a persisted file is closed.

**Costs, accepted.**

- **A transient blip now fails the screen where a retry might have hidden it.** That is the intent — the screen is a measurement — and it is a real change: one flaky response is now one red run.
- **`--check-judge` gets slower to interpret and longer on screen.** Three columns per arm instead of one glyph.
- **Diagnostic detail is lost from error text.** An SDK exception that carries a useful provider message now reports only its type. Accepted for the same reason ADR-0037 dropped the endpoint path: a message is not safe merely because it usually is.
- **The eval path loses retries too.** `Judge` is one class and both callers get `max_retries=0`. A full judged run is now more exposed to a single bad response. Deliberate: ADR-0036 already makes an unjudged case `SKIP` rather than a failure, so the cost is an unmeasured case, not a false regression — and an invisible retry in a judged run is exactly the thing that would make `groundedness` coverage unreadable.

**Unchanged and load-bearing.** **ADR-0037 in every respect** — the self-judging comparison, the trust levels, `sanitise_endpoint`, the qualification-versus-functioning split, and the rule that an untrusted judged metric satisfies no requirement. ADR-0036's four outcomes, exit codes, `--require` and `--fail-on-unmeasured`. Every threshold, dataset, case expectation, prompt, graph, tool and model configuration. `neura-llm`, untouched. **`report_schema_version` stays 3**: `Verdict` is never serialised — only `Check.status` and `Check.detail` reach the file — so no persisted structure changes.

**This ADR selects no judge and qualifies none.** The Nemotron candidate remains **unqualified** and its screen remains **failed**. What changed is that the instrument can now be believed.

## Alternatives considered

**Keep the AND and fix only the message.** Rejected. The message was the smaller defect; a red cross over a correct refusal teaches the reader that the judge cannot refuse.

**Count an `ERRORED` arm as a failure and keep two states.** Rejected — it is ADR-0036's rejected *"count an unmeasured case as failed"* in miniature. It states an outcome that was never measured, and it would send an operator to replace a judge when the fault is a provider.

**Count an `ERRORED` arm as a pass so a flaky provider does not block.** Rejected outright. That is a false green on the one command whose job is to refuse them.

**Leave `max_retries` at the SDK default and just report `retries_taken`.** Rejected as the default for a probe. Reporting the number is strictly better than not, and `APIResponse.retries_taken` makes it available — but a probe whose request count varies run to run cannot be budgeted against a 50-per-day tier, and the variance would land inside the consistency measurement Step 2 is supposed to isolate.

**Add a bounded application-level retry now, since the provider is evidently flaky.** Rejected, and explicitly out of scope on the owner's decision. Retrying is a policy about spending quota; deciding it in the same change that discovered we could not count quota would repeat the mistake in the other direction.

**Set `_strict_response_validation=True` so a malformed body raises inside the SDK.** Rejected: it changes how *every* response is parsed, converts tolerable schema drift into hard failures across the whole judged path, and the explicit check costs two lines and names the fault better than a Pydantic traceback would.
