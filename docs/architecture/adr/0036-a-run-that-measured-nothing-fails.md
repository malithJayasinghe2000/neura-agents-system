# ADR-0036 — A Run That Measured Nothing Fails, And A Missing Gate Is A Failure

**Status:** **Accepted** — owner decision, 2026-09-06 · **Date:** 2026-09-06 · **Builds on:** [ADR-0033](0033-care-answers-what-the-store-has-sell-helps-the-shopper-choose.md) §3, [ADR-0011](0011-deterministic-guard-not-classifier.md) · **Upholds and extends** ADR-0033 §3; supersedes nothing · **Resolves:** [E9](../../open-questions.md)

## Context

On 2026-09-06 Ollama became unreachable partway through `make eval`, and the `make eval-guard-off` run that followed reached no model at all. It printed the correct warning and then contradicted it two lines later ([Finding 27](../../TESTING_LOG.md)):

```
│ 47 of 47 cases could not reach the model provider.                           │
│ Those cases are SKIPPED, not failed — they were never measured.              │

  cases       47  (47 passed, 0 failed)

  metric                    value    gate           cases
  structured repair rate     0.00    0.05    ✔       47/0
```

The persisted report agreed with the wrong half — `total: 47, passed: 47`, every case `"passed": true` — **`injection resistance` was absent from the metrics table entirely**, not `0.00`, and the process **exited 0**. [AGENTS.md](../../../AGENTS.md) says of that exact command *"injection resistance must be 1.00 in it"*, and calls it *"a release blocker, not a target"*.

**It happened twice on one afternoon, by two different mechanisms**, and the second is the sharper one. On `cloud-prod` the OpenRouter free tier hit `Rate limit exceeded: free-models-per-day` and refused all 47 guard-off cases. That report printed **`injection resistance 1.00 ✔`** — because a turn that never reaches a model proposes no tool, so `unauthorised_tool_calls` is zero by arithmetic. **That is AGENTS.md's own stated failure mode for this command** — *"a guard that blocks can MANUFACTURE the injection-resistance gate"* — with a quota standing where the guard stands. A rate limiter is indistinguishable, in the report, from a defence working.

### Six defects, and each was individually defensible

1. **`CaseResult.passed` was `not any(check.failed)`.** A case whose only check was `execution: SKIP` had no failed check, so it passed. Outcome was a boolean, and *"not measured"* had nowhere to live but a caveat the headline contradicted.
2. **`summarise()` printed `total - passed` as "failed".** With nothing measured that is 0.
3. **A metric never emitted has no gate to fail.** `gate_failures()` iterates `THRESHOLDS` and skips what is absent — which is correct, and is ADR-0033 §3. Nothing then asked whether a metric that *had* to exist did.
4. **`--fail-on-gate` was opt-in and no `make` target passed it.** The same suite's `groundedness 0.78 ✘` and `tool selection 0.41 ✘` also exited 0.
5. **`ProviderRateLimitedError` was not classified as a provider failure at all.** It is a *sibling* of `ProviderUnavailableError` under `LLMError`, not a subclass, and `unreachable_provider()` matched two type names by string. So a quota exhaustion was scored as agent behaviour.
6. **`structured_repair_rate` was computed over cases that never ran.** `ran` excluded `--no-agent` and not `infrastructure_error`, so 47 dead cases fell through the `max(1, …)` fallback to `0/47 = 0.00 ✔`. It was the only metric that run emitted, and it was green.

**This is the fourth appearance of one failure**, and the shape is identical every time: Finding 12, Finding 23, the 2026-08-27 `tool_selection_accuracy` vacuum, and this. **A check that stops checking, and says green.**

## Decision

> **A case that did not reach a result is neither passed nor failed. A run that was required to measure something and did not, fails. And the exit code says which kind of failure it was.**

### 1. Four outcomes, derived and not stored

| outcome | meaning |
|:--|:--|
| `PASSED` | ran, and every assertion held |
| `FAILED` | ran, and an assertion did not — **the only outcome about the agent** |
| `ERRORED` | never reached a result: provider unreachable, rate limited, or the target raised |
| `SKIPPED` | deliberately not run — `--no-agent`, or a target that does not apply |

`CaseResult.outcome` is a **property**, computed from the same three response fields the branches in `score_case` already read. It cannot disagree with them, and an unmeasured case cannot be constructed as a pass. `passed` survives with its meaning narrowed to `outcome is PASSED`; `failed` and `measured` are new.

`total == passed + failed + errored + skipped` is asserted inside `summarise()`, not only in a test — an outcome added later without a counter would otherwise vanish into the gap, which is exactly how *"47 passed, 0 failed"* happened.

**`pass_rate` is now stated against `measured`, not `total`.** 47 over 47 unmeasured was a pass rate of 1.0.

### 2. A required metric must be produced, and absence is its own failure

`--require METRIC`, repeatable. The metric must be **emitted**, and if it has a threshold, must **meet** it. `RunSummary.missing_required()` answers absence; `gate_failures()` continues to answer breach, and continues to say nothing about a metric that does not exist.

**ADR-0033 §3 is upheld rather than reversed.** A suite that tags nothing still emits no metric rather than a vacuous `0.00` that passes by measuring nothing. What changes is that *the caller may now declare that it needed the number*, and the run fails when it is not there. Those are different questions and both answers are needed: the first keeps a meaningless number out of a report, the second keeps a missing one from being read as consent.

**Which metrics are required is the caller's, never this module's.** It depends on which datasets a run was pointed at — CARE's suite must produce `injection_resistance`; the dispatch suite cannot, and must produce `expensive_misroute_rate` instead. A single answer baked into the harness would be wrong for one of them.

A `--require` naming a metric the harness can never emit is a **usage error** (argparse's exit 2), not a command that fails for ever for a reason nobody can act on.

### 3. Only the release blocker blocks; every other gate stays reported

`make eval` and `make eval-guard-off` require **`injection_resistance` and nothing else**, and the shortness of that list is the decision rather than an oversight.

**Passing `--fail-on-gate` on those targets was considered and rejected.** `tool_selection_accuracy` fails today for documented reasons (A7, A14), and `make eval-guard-off` **fails escalation precision by design**. A command that is permanently red is a command whose red stops meaning anything — the same rot as one that is falsely green, arriving from the other side. Raising the thresholds to fit would be inventing a number to be met, which [CLAUDE.md §4](../../../CLAUDE.md) exists to prevent.

So the distinction AGENTS.md already draws in prose — *"a release blocker, not a target"* — is now the distinction the code makes, and `--fail-on-gate` remains available for a run that wants everything.

`groundedness` is deliberately **not** required: the free judge tier legitimately runs out ([E2b](../../open-questions.md)), and a legitimately-absent metric must not fail a run.

### 4. A partial suite is not a release run

`--fail-on-unmeasured` fails a run in which any case ERRORED. No tolerance, and the reason is that a suite of 40 measured cases compared against one of 47 is E9's cousin: a number that is real, narrower than it looks, and read as though it were not.

### 5. Exit codes name the kind of failure

| code | meaning |
|:--|:--|
| `0` | ran, and met everything it was required to meet |
| `1` | **about the agent** — a required metric was missing, or a gate was not met |
| `2` | a CLI usage error (argparse's own) |
| `3` | **about the infrastructure** — a case never reached a result |

**Infrastructure outranks the gate**, and that ordering is deliberate: a run that could not reach the model has numbers that mean nothing, so reporting *"injection resistance missing"* as the headline would send somebody to look at the datasets. The provider is the thing to fix.

### 6. A rate limit is a provider failure

`ProviderRateLimitedError` joins `ProviderUnavailableError` and `ProviderTimeoutError` in the set `unreachable_provider()` matches. What that set means is *the provider produced no answer*, and a refusal for quota is one.

Nothing a shopper experiences changes: every call site already merges `infra_error()` with an escalation, and no route in `apps/` reads the field. What changes is that the eval harness can tell an outage from a decision.

### 7. `verify` marks a provider failure, without changing what it does

`route` and `plan` marked themselves and `verify` did not, so a provider dying at the last node produced a turn that escalated with no marker — scored by the suite as an escalation the agent chose, costing escalation precision for an outage.

`verify` now merges `infra_error(exc, …)` into its failure branch. **`_ungrounded` still runs first and always**, so the fail-closed behaviour is untouched: the draft is not sent, whatever the cause. And the marking is narrow by construction — `infra_error` returns `{}` for anything that is not a provider failure, so a model emitting unparseable JSON stays scored as the agent decision it is. Marking *every* verification exception as infrastructure would delete the evidence `structured_repair_rate` and [ADR-0018](0018-guard-model-must-refuse.md) exist to collect.

### 8. The report file cannot present a false green

`report_schema_version: 2`. Every case carries `outcome`; the summary carries all four counts and `measured`; and the file carries `ok`, `exit_code`, `required_metrics`, `missing_required` and `failure_reasons` — so a machine reader needs one field rather than a rule for combining five.

**Version 1 files record `passed: true` for cases that reached no model.** The number is there to say which meaning the field carries.

### 9. Reproduced by a stub, never by an absent model

Every regression test drives a **deterministic stub provider**: at the harness seam for the scoring, summary, gate and exit-code paths, and at the graph seam — the real CARE graph, with a stubbed LLM raising the real exception types — for the classification in §6 and §7.

E9 was *found* by Ollama dying mid-suite. A test that reproduced it that way would only run on a bad afternoon.

## Consequences

**Good.** `make eval` and `make eval-guard-off` can no longer exit 0 having measured nothing, and AGENTS.md's *"injection resistance must be 1.00 in it"* is enforced by the command rather than by a human reading a table. The two failure modes that produced identical green reports — an absent metric and a manufactured one — now produce different, loud, non-zero results. A report file six weeks old can be told from a clean one.

**Costs, accepted.**

- **A flaky provider now fails the command.** A run that dies at case 40 of 47 exits 3 where it used to exit 0 with a caveat. That is the intent, and it is a real change to the developer experience.
- **`pass_rate` and per-case `passed` change meaning.** Mitigated by the schema version; `evals/reports/` is gitignored and read by nothing programmatic, and `make eval-compare` reads only `summary.metrics`.
- **Two existing test assertions were flipped**, and both had messages stating the bug as the intent (*"an unmeasured case is not a failure"* — half right, and the missing half was Finding 27). They are rewritten to say both halves.
- **Six gates stay reported and unenforced.** This ADR does not fix `tool_selection_accuracy 0.41`; it makes sure a run cannot hide it by measuring nothing. Enforcing those is a separate decision that needs the numbers to be met first.

**Unchanged and load-bearing.** ADR-0033 §3 — a suite that tags nothing still emits no metric. Every threshold in `THRESHOLDS`. Every dataset and every case expectation. CARE's and SELL's prompts, graphs, tools and model configuration. The shopper-facing behaviour of every turn, including every turn a provider failed during. `make eval-fast` and therefore `make check`, where every case is `SKIPPED` rather than `ERRORED` and the exit code stays 0.

## Alternatives considered

**Pass `--fail-on-gate` on both `make` targets.** Rejected — §3. It would make both commands permanently red on documented, accepted failures, including one that `make eval-guard-off` has by design.

**Raise or remove the thresholds that fail today.** Rejected outright. That is inventing a number to be met, and it would make the release gate agree with whatever the agent currently does.

**Count an unmeasured case as failed.** Rejected, and it was the first version of `NotImplementedTarget` before it was reverted for the right reason: it states an outcome that was never measured, and it puts thirty-five red crosses into `make check`, which runs before every push. A command that is always partly red is a command whose red stops meaning anything.

**Emit `injection_resistance: 0.00` when no case measured it, so the existing gate catches it.** Rejected — it is exactly the vacuous number ADR-0033 §3 refused, and it would report *"the defence failed"* when what happened is that nobody asked.

**Make the harness decide which metrics are required.** Rejected — §2. It would have to know which datasets exist and which agent produces which metric, and `expensive_misroute_rate` already establishes that the harness learns severity from the dataset rather than inferring it.

**Fold exit 3 into exit 1.** Rejected on the owner's decision. A CI job that cannot tell *"the agent regressed"* from *"the model server is down"* retries the first for ever and pages nobody for the second.
