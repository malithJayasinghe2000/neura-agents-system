# ADR-0037 — A Model May Not Grade Its Own Answer

**Status:** **Accepted** — owner decision, 2026-09-12 · **Date:** 2026-09-12 · **Builds on:** [ADR-0036](0036-a-run-that-measured-nothing-fails.md), [ADR-0006](0006-llm-model-roles.md) · **Completes** ADR-0036 in the judged dimension; supersedes nothing · **Resolves:** [E11](../../open-questions.md)

## Context

Found on 2026-09-06 while configuring the live ADR-0036 validation, and it was nearly missed.

`.env` sets `CLOUD_MODEL_ROUTER`, `_REASONER`, `_GUARD` and `_SUMMARIZER` to `gemini-3.6-flash`, and `EVAL_JUDGE_MODEL` to `gemini-3.6-flash`. So a judged `make eval --role-map cloud-prod` would have **the model grading its own answer** — and reported the score as `trusted`.

### The two halves are resolved separately and never introduced

| | resolved by | from |
|:--|:--|:--|
| agent models | `LLMClient.from_role_map_name(args.role_map)` | `CLOUD_MODEL_*` |
| judge model | `judge_from_env()` | `EVAL_JUDGE_*` |

They were built two lines apart in `__main__.py` and never compared. `judge_from_env()` takes no arguments; it cannot see the role map, so it decided trust from the model *name* alone:

```python
trust = JudgeTrust.UNTRUSTED_WEAK_MODEL if _looks_weak(model) else JudgeTrust.TRUSTED
```

`gemini-3.6-flash` matches no weak-model marker, so: **`TRUSTED`**.

### The state that was declared and never reachable

`JudgeTrust.UNTRUSTED_SELF_JUDGING` has existed since milestone 1.4. **Nothing in the repository ever set it.** [evaluation-strategy.md §3.1](../evaluation-strategy.md) documents it in a table of trust levels as though it were implemented, and `judge.py`'s own module docstring states the rule the code did not enforce: *"never the same small local model being evaluated."*

**This is the house failure mode in the one place whose entire job is to refuse it** — `config.py` already carries a comment about a hosted 9B that *"would have been labelled trusted"*, and the same gap existed one level up.

### Which model actually writes the graded text

`Judge.grounded(reply=..., evidence=...)` scores `response.reply`. Two roles are correlated with that text:

| role | relationship | risk when the judge is this model |
|:--|:--|:--|
| **REASONER** | `compose` wrote the draft on it | self-preference — a model rates its own output higher |
| **GUARD** | `verify` already ruled it grounded | the judge re-runs a check the same weights already passed |

On `cloud-prod` both are the judge's model at once.

## Decision

> **A judged metric produced by a model that also serves any role in the run under test is reported, labelled `untrusted:self-judging`, and may never satisfy a required metric. A run that was required to produce it fails with exit 1.**

### 1. Compared against every configured role

`_models_in_play()` collects `model_for(role)` for every `ModelRole` in the active map. A match with **any** of them is self-judging.

Fail-closed, and the surgical alternative was considered: only `REASONER` and `GUARD` touch the graded text, so only they can bias a verdict. Comparing against all of them always includes both, costs nothing, and cannot be wrong in the dangerous direction.

**Inspection is tri-state, because "we found nothing" and "we could not look" are different facts.** `RoleMapModels` carries `models` *and* `inspected`:

| state | meaning | trust |
|:--|:--|:--|
| `inspected=True`, empty | nothing ran — `--no-agent`, or an injected target | unchanged; nothing was self-judged |
| `inspected=True`, populated | the models are known | compared |
| `inspected=False` | the map could not be read | **`untrusted:unverified`** |

**Only `RoleNotConfiguredError` means "this role is not configured".** It is what `RoleMap.resolve()` raises for all three legitimate cases — an undefined role, an unknown provider, an unset environment variable — so it is skipped. **Anything else is a defect**, and the first version of this code caught `Exception` and returned `None`, which became an empty set, which the comparison read as *"matches nothing"*, which printed **`trusted`**. A detector whose failure mode is "everything is fine" is not a detector.

`UNTRUSTED_UNVERIFIED` is non-qualifying exactly as the other two are. It is kept distinct because the fix differs: this is a misconfiguration or a defect to go and find, not a judge to replace.

**The eval is not destroyed by it.** An inspection failure makes the *judge qualification* unknown; the mechanical metrics — `injection_resistance` above all — are unaffected and still worth having. Losing a whole suite because a qualification could not be computed would trade a real measurement for a labelling problem. A role map that cannot be **built** at all is different: no case can run, so the run exits 3 with a clear message rather than a traceback.

### 2. Identity is a normalised model name, and the endpoint is not part of it

Normalisation strips surrounding whitespace, casefolds, and removes **only** the recognised terminal `:free`.

**Endpoint-independent, deliberately.** The same weights reached through two gateways self-judge identically, so requiring base URLs to match as well would miss the most plausible way to configure this by accident. The endpoint is still *recorded* — a human needs to see the arrangement — it simply does not gate the decision.

**Why `:free` and nothing else.** `openrouter/x:free` and `openrouter/x` are the same route billed differently, so a judge on the free tier of the model under test is still marking its own homework. A **tier** suffix names the same route; a **vendor prefix** names a different one.

### 3. What is deliberately not matched, and is a stated limitation

| not matched | why not |
|:--|:--|
| `google/gemini-3.6-flash` vs `gemini-3.6-flash` | two gateways can mean different things by the same bare name. Stripping the namespace is a guess |
| other gateway aliases | same reason, no general rule exists |
| `gemini-3.6-flash` vs `gemini-3.5-flash` | different models. Merging them would disqualify a judge that is genuinely independent |
| same vendor family | a correlation worth knowing about and not the same claim |

**These are gaps, recorded rather than papered over**, and each has a negative test so the omission is deliberate and visible rather than discovered later.

### 4. Reported, labelled, and qualifying for nothing

A self-judged score is not worthless — a groundedness of 0.40 still says something is badly wrong — it is biased by an unknown amount in a known direction. So it is kept and disarmed:

- the value is computed and printed;
- `groundedness` appears in `RunSummary.untrusted_metrics`;
- the metrics table prints **`untrusted`** *in place of* the ✔/✘, because a tick beside a self-judged score is what gets skim-read as "met";
- it can never satisfy `--require groundedness`;
- requiring it exits **1**, not 3 — every case reached a result, so this is not ADR-0036's unmeasured-run condition. The run simply did not produce the evidence it was required to produce.

**No `--allow-self-judging` flag.** An opt-in would imply that not passing it is safe, when the unsafe thing is the configuration.

The same disqualification applies to `UNTRUSTED_WEAK_MODEL`, which previously could satisfy a requirement while wearing a warning label. The rule is about trust, not specifically about self-judging.

### 5. One client, and the evaluator still does not know any agent's name

`__main__` builds the `LLMClient` **once** and passes that same client to the target discovered through the `neura.eval_targets` entry point. Two clients would be two answers to *"which models is this run using?"*, and the one that mattered would be the one nobody looked at.

`judge_from_env()` stays ignorant of the role map. It is *told*, afterwards, by `resolve_judge_trust(config, agent_models)` — a pure function that only ever downgrades. Nothing in `neura-evals` learns an agent's name, no target changes, and `neura-llm` is untouched.

### 6. `--check-judge` separates functioning from qualifying

Two different questions, and the command used to answer only the first while printing an answer to the second:

- **Does it function?** Reachable, accepts a grounded reply, catches a hallucination. **This decides the exit code**, because it is what the command is for.
- **Does it qualify?** Printed beside it, never folded into the tick. A functioning judge that serves a role in the map is reported `✘ NOT QUALIFIED`, and the closing line reads *"FUNCTIONING but NOT QUALIFIED"* rather than a bare *"Judge is working."*

It takes `--role-map` for this reason. **It does not degrade to reporting on the judge alone**: an uninspectable map prints `✘ QUALIFICATION UNKNOWN` with the underlying error and **exits 1 before making a single judge call**. Spending API quota to learn that a disqualified judge *functions* would bury the thing the operator has to fix, and the earlier draft's fallback — report on the judge, say nothing about the map — is precisely how an empty model set came to read as independence.

### 7. A persisted endpoint carries no credentials

`sanitise_endpoint()` persists **the origin and nothing else** — scheme, host, and a valid port:

| dropped | why |
|:--|:--|
| user information | `https://user:secret@host/` is a legal base URL |
| query string | plenty of gateways accept `?key=…` |
| fragment | the same, and it survives copy-paste |
| **the path** | a generic gateway may route by a secret in a path segment (`/v1/sk-live-…/openai`). A path is not safe merely because it usually is, and *"which product"* is not worth the class of leak — the host already answers *"which vendor"* |

**It cannot raise.** `urlsplit` defers port validation to attribute access, so `https://host:notaport/v1` throws `ValueError` on `.port` — which the first version read *outside* its own `try`, making the sanitiser a source of crashes on exactly the malformed input it exists to handle. Both the parse and the port read are now protected, and anything malformed degrades to the empty string rather than to the raw value: the failure has to be safe in the direction of saying less.

IPv6 literals are re-bracketed, because `hostname` strips them and `http://::1:11434` is not a URL.

A report written before 2026-09-12 may contain a path in `judge.endpoint`; nothing rewrites those.

### 8. Older reports cannot be assumed independent

Report schema goes to **3**. In schemas 1 and 2, self-judging was never checked, so **`judge.trust: "trusted"` in an older file is not evidence that the judge was independent** — it means only that the model name matched no weak-model marker.

**Any groundedness figure in a schema<3 file may have been self-judged and must not be quoted without checking what the role map was.** No file is rewritten and none is deleted; the version number is what makes the distinction answerable.

The two accepted live runs of 2026-09-06 are unaffected: both passed `--no-judge` and produced no groundedness figure at all.

## Consequences

**Good.** The trust level that has been documented since 1.4 is now reachable, and the one configuration this project actually has can no longer report a self-graded number as evidence. `--check-judge` cannot describe the current `.env` as trusted. A judged metric joins the ADR-0036 family: present, absent and *present-but-not-believable* are three distinguishable states with three different consequences.

**Costs, accepted.**

- **`A9` stays parked, and now for a nameable reason.** Measuring groundedness on `cloud-prod` needs a judge that serves no role in it. That is a model selection with compatibility, quality and cost to compare — deliberately **not** made here.
- **The vendor-prefix gap is real.** A judge configured as `google/gemini-3.6-flash` against an agent on `gemini-3.6-flash` is self-judging and will not be detected. Recorded, tested as a known negative, and preferred to a guess.
- **Over-detection is possible in principle** — two genuinely different models sharing a normalised name — and would wrongly disqualify a judge. Bounded by exact-name comparison and, today, by nothing requiring `groundedness`.
- **A second thing to keep working.** A detector that silently stopped detecting would be `tool_selection_accuracy`'s 2026-08-27 failure again, so the models compared against are printed by `--check-judge`, and an inspection that fails says so instead of returning nothing.
- **Diagnostic detail is lost from `judge.endpoint`.** It records `https://host` where it used to record the full path. Accepted: the host identifies the vendor, and a path can carry a credential.

**Unchanged and load-bearing.** ADR-0036 in every respect — the four outcomes, the exit codes, `--require`, `--fail-on-unmeasured`. Every threshold. Every dataset and case expectation. CARE's and SELL's prompts, graphs, tools and model configuration. `neura-llm`. The `EvalTarget` protocol and every target. Entry-point discovery. `RunReport.is_validation`, which means *"at least one case is non-synthetic"* (E1) and is **deliberately not coupled** to judge trust — they are independent questions and merging them would make both unreadable.

**Blast radius today is zero.** Neither `make eval` nor `make eval-guard-off` requires `groundedness`, so no current command changes its exit code. This relabels, and it bites the day someone adds `--require groundedness` — which is exactly when it should.

## Alternatives considered

**Refuse to run at all when the judge serves a role.** Rejected: a self-judged score is biased, not worthless, and refusing turns a labelling problem into an outage the moment somebody points both at one model.

**Mark it untrusted and let it keep satisfying gates.** Rejected — that is ADR-0036's false green wearing a number instead of a gap. A label a machine ignores is not a control.

**Require the endpoint to match as well.** Rejected — §2. It would miss the same weights reached through two gateways, which is the likeliest accident.

**Strip vendor prefixes so `google/x` matches `x`.** Rejected — §3. It assumes two namespaces mean the same thing by the same bare name, which is a guess about routing this repository cannot verify.

**Compare only `REASONER` and `GUARD`.** Rejected as the default — §1. More precisely argued, and it would let a map that shares the judge's model on `ROUTER` alone report trusted. Fail-closed is cheaper than being right.

**Have `judge_from_env()` read the role map itself.** Rejected: it would couple configuration loading to whichever run happens to be in progress, and `--role-map` is a command-line argument that `.env` does not know about.

**Treat any inspection failure as "no models" and carry on.** Rejected — it is the fail-open edge this ADR was amended to close. An empty set is indistinguishable from `--no-agent`, which is legitimately trusted, so a crashing detector would have reported every self-judging run as independent.

**Abort the whole eval when inspection fails.** Considered and rejected as the default. It throws away valid mechanical measurements — including the release-blocking one — because a *label* could not be computed. The run continues, the qualification is `untrusted:unverified`, and nothing it produces can satisfy a requirement.

**Keep the path in the persisted endpoint.** Rejected — §7. Gateways exist that route by a secret in a path segment, and a sanitiser has to be right about the general case rather than the common one.
