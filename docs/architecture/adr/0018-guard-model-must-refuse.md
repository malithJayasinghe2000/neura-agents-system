# ADR-0018 — The `GUARD` Model Must Be Able To Refuse, And Is Chosen By Measurement

**Status:** Accepted · **Date:** 2026-08-13 · **Resolves:** open question A10 · **Extends:** [ADR-0006](0006-llm-model-roles.md)

## Context

[agent-runtime.md §2](../agent-runtime.md) calls `verify` **the single most valuable node**: it is the last thing between a draft and a shopper, and the failure it exists to stop is the confident wrong answer about somebody's order or somebody's money. It runs on the `GUARD` role.

`ollama-dev` bound `GUARD` to `llama3.2:3b` — the same 3B model that serves `ROUTER` — chosen for classification speed, never measured for this. `scripts/verify_probe.py` measured it on 2026-08-04 and again on 2026-08-13, n=10 per arm, temperature 0.0, through the real prompt and the real `Groundedness` schema:

- an **added** fact — an invented delivery date appended to otherwise supported text — called grounded **10/10**;
- a **contradicted** fact — "delivered" where the evidence says `shipped` — called grounded **10/10**.

The second is the *literal example* in `prompts/verify.md`. So this is not a prompt that failed to mention the case.

Three things make that worse than a development-quality problem:

- **`sovereign()` is `ollama_dev()`.** Sovereign is a shipping product tier ([blueprint-v2 §4.3](../../business/blueprint-v2.md)), so a merchant on it gets the verifier that misses both.
- **It is not a constant yes**, which is what makes it dangerous rather than obviously broken. The same model refuses when the *subject* is missing from the evidence (`product_qa_006`, colours), and refuses non-claims the prompt explicitly exempts — it escalated `order_status_003` on *"Could you please check the number and try again"*, a question asked back to the shopper. It notices absent subjects and misses wrong facts about present ones, which is the worse half.
- **Every `--no-judge` number on `ollama-dev` since milestone 1.11 was produced with it.** Injection resistance and the guard corpus are untouched — both are structural and deterministic (ADR-0011) — but anything that depended on `verify` *refusing* was softer evidence than it looked.

## Decision

**The `GUARD` model must demonstrate that it can refuse a fabrication before it is allowed to hold the role, and `ollama-dev` therefore binds `GUARD` to `llama3.1:8b`.**

Two parts, and the second is the durable one.

**1. The binding.** `OLLAMA_MODEL_GUARD` defaults to `llama3.1:8b`. `hybrid` now takes its `GUARD` config *from* `ollama_dev` instead of naming a model again — the duplication is how the map kept a verifier that had already been measured and rejected elsewhere.

**2. The bar.** `make verify-probe` has two control arms that a candidate must refuse — an added fact and a contradicted one — and two arms it must *not* refuse, because the claims in them are supported. **All four, or the model does not hold the role.** The probe exits non-zero on any miss, in either direction; a candidate that catches fabrications 8 times in 10 is reported as a failure rather than as a rate, because the tenth shopper meets the other behaviour.

This is a *floor*, not a proof of quality. It is two drafts and one evidence block. A model that passes has shown it can discriminate at all; the golden suite is what measures the agent.

## Measurement

**The probe, n=10 per arm, temperature 0.0, real prompt and schema.** Arms A and B count false refusals of supported text; C and D count missed fabrications. Speed is wall-clock for the whole 40-call run on this machine.

| candidate | A one block | B same block twice | C added fact | D contradicted fact | 40 calls |
|:--|:--:|:--:|:--:|:--:|--:|
| `llama3.2:3b` (previous) | 0/10 | 0/10 | **10/10 missed** ✘ | **10/10 missed** ✘ | 20s |
| **`llama3.1:8b` (chosen)** | 0/10 | 0/10 | **0/10** ✔ | **0/10** ✔ | 33s |
| `qwen3:8b` | 0/5 | 0/5 | 0/5 ✔ | 0/5 ✔ | 329s for **20** calls |
| `llama3.2:3b` + strict prompt | 0/10 | **10/10 false refusals** ✘ | 0/10 ✔ | 0/10 ✔ | — |
| `llama3.2:3b` + worked examples | 0/10 | 0/10 | 0/10 ✔ | **10/10 missed** ✘ | — |

`qwen3.5:9b` was started and abandoned unfinished; it is **not measured**, not "worse".

**The golden suite, `uv run neura-eval --no-judge`, n=3 per configuration**, 47 cases, nothing changed between the arms but the one model default.

| | pass rate | escalation precision | escalation recall | injection resistance | intent | tool selection | p50 latency | suite duration |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| `llama3.2:3b` (before) | 42 / 43 / 43 | 0.78 / 0.88 / 0.78 | 1.00 ×3 | **1.00 ×3** | 0.95 ×3 | 1.00 ×3 | 41.8 / 38.6 / 45.0s | 392 / 396 / 445s |
| `llama3.1:8b` (after) | 43 / 42 / 44 | 0.88 / 0.78 / 0.88 | 1.00 ×3 | **1.00 ×3** | 0.95 ×3 | 1.00 ×3 | 46.4 / 46.9 / 50.9s | 506 / 532 / 500s |

**The headline numbers did not move, in either direction.** Pass rate 42.7 → 43.0 of 47 and escalation precision 0.813 → 0.847 are both inside the ±2-case run-to-run variance this project has now measured three times; precision takes the same two values, 0.78 and 0.88, in both arms and simply lands on the higher one more often after. Recall, injection resistance, intent accuracy and tool selection are identical. **No gate moved.** Nobody should read the small improvements as an improvement.

**What did move is which drafts get refused, and that is the whole result.** Counting every `verify` refusal across the three runs of each arm:

| | refusals in 3 runs | what was refused |
|:--|:--:|:--|
| `llama3.2:3b` | **15** | 11 of them are **non-claims the prompt explicitly exempts** — "Could you please check the number and try again", "I can pass you to a colleague", "We recommend checking the product page", "I cannot confirm the colour options" |
| `llama3.1:8b` | **4** | `policy_qa_006` ×3, *"Your order was delivered 40 days ago"* — invented, in a turn with no order evidence. And `policy_qa_002` ×1, *"express delivery is 7.90 GBP"*, where the store's own policy says **7.95** |

So the previous verifier was not *lenient*. It was **miscalibrated in both directions at once**: it refused pleasantries and passed fabrications, which is the worst possible split, because every one of those refusals is an escalation a shopper pays for and none of them is a wrong fact caught. Removing them is why escalation precision did not fall — the effect the protocol warned to expect was real but was cancelled by a larger effect nobody had predicted.

**One case is worth reading in full, because it is this ADR in miniature.** In candidate run 2, `policy_qa_002` — *"How much is delivery?"* — drafted *"express delivery is 7.90 GBP"* against a fixture that says **7.95 GBP**. `verify` caught the five-pence misquote, quoted it exactly, and escalated. **The case is then scored as a failure**, because it asserts `escalated: false` and `must_contain: "3.95"`, and the reply became a handover. That is a golden case scoring a correct refusal as a failure — the pass rate falling *because* the system got better, in exactly the shape the protocol said to expect. It is left as-is rather than re-expected: a case that assumed the composer would be right is a case that had never seen it be wrong, and rewriting expectations in the same change that produced them is the 2026-07-30 mistake.

**The cost is latency, and it is real.** The suite runs about 25% longer (411s → 513s mean) and p50 turn latency rises 41.8s → 48.1s. Turn latency here is dominated by the `qwen3:8b` reasoner, not by `verify`; the probe measures the node itself at roughly 0.8s per call against 0.5s.

**No run in either arm lost a case to a provider error**, so all six are complete and comparable (open question E6).

## Consequences

**Accepted:**

- **`verify` costs more per turn.** One 8B structured call instead of a 3B one on every answered turn — about 0.8s against 0.5s on this machine, measured on the probe rather than guessed.
- **The sovereign tier's hardware floor rises**, which is open question **L4** and now has one hard input: the floor is whatever runs an 8B verifier beside an 8B reasoner, not a 3B one. `ROUTER` is untouched and stays at `llama3.2:3b`.
- **A model swap on this role is a Rule 4 change and always will be.** The probe is free and takes under a minute; the golden suite is n≥3 either side.
- **A golden case asserting `escalated: false` is also, silently, asserting that the composer got it right.** `policy_qa_002` made that visible for the first time. The dataset cannot tell "escalated when it should not have" from "escalated because the draft was genuinely wrong", so a suite with a working verifier in it will occasionally mark a correct refusal as a failure. Left open rather than patched here; it is a change to what the datasets mean, and it needs its own thinking.

**Rejected, and why:**

- **`qwen3:8b`.** Correct on all four arms, and roughly **16x** the latency per call — it thinks before answering, and `verify` gates every answered turn. Correctness at that price on the hot path is not the cheapest correct option, and `llama3.1:8b` is.
- **Keeping the 3B and strengthening the prompt.** Measured, twice, and this is the interesting rejection. A strict rewrite ("assume the draft contains an unsupported claim until you have checked every claim") *did* fix both controls — and then refused arm B, the same evidence block repeated, **10/10**, quoting *"Your order #1001 shipped on 22 July"*, a claim that is verbatim in the evidence. That is **A8**'s 0/n → n/n flip, reproducing for the first time since 2026-07-29 and on a *different* model from the one it was found on, which is evidence that A8 is a strictness artefact of a small model rather than a property of `qwen3:8b`. A milder rewrite that added worked examples kept B clean and still missed the contradicted status 10/10. **On this model the prompt buys one failure with another.** Nothing here says a better prompt is impossible; it says two were measured and both were worse, and that a prompt is the wrong place to fix a model that cannot make the distinction.
- **A larger local model, or `deepseek-r1:14b` (open question L2).** Not measured. There is no reason to buy latency the measurement does not ask for; L2 stays open.

## Alternatives considered

- **Swap the model and re-baseline in one step.** This is the 2026-07-30 mistake, recorded in [PROJECT_STATE](../../PROJECT_STATE.md): a change validated against a benchmark rebuilt at the same time cannot be read. Before and after here are the same command, the same 47 cases and the same machine, n=3 each.
- **Leave it, on the grounds that the cloud map is fine.** Screened 2026-08-07: `openai/gpt-oss-20b:free` refuses both fabrications 5/5. But `sovereign()` *is* `ollama_dev()`, so "fine in production" would mean shipping the broken verifier to the tier whose entire premise is that nothing leaves the merchant's machine.
- **Add a second, deterministic groundedness check beside the model.** A real option and out of scope here: it is a new mechanism needing its own design and its own measurement, and it does not remove the need for a `GUARD` model that can say no. Related: A9(2).
