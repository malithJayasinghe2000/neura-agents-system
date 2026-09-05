# ADR-0033 — CARE Answers What The Store Has; SELL Helps The Shopper Choose

**Status:** Accepted — the rule and the gate are decided; **no declaration and no prompt is changed by this ADR** · **Date:** 2026-09-05 · **Builds on:** [ADR-0031](0031-the-shopper-never-chooses-the-agent.md) · **Answers:** [A19](../../open-questions.md), and sets the release gate ADR-0031 left open

## Context

[ADR-0031](0031-the-shopper-never-chooses-the-agent.md) shipped dispatch **without a release gate**, deliberately: a threshold drawn from sixteen cases written the same week would have been a number invented to be met. Two things were left open — the gate, and **[A19](../../open-questions.md)**: *when both agents can answer, which one should?*

**The overlap is real and neither declaration is dishonest.** CARE's `prompts/route.md` gives `product_qa` as *"availability, price, sizes, materials, stock, comparisons, **recommendations**"* — CARE genuinely answers shopping questions. SELL's `handles` claims only *"helping a shopper find or choose a product they have not bought yet"*. Both are accurate.

**The rule was already encoded in the dataset and decided nowhere.** `dispatch.yaml` says so about itself:

> *"The split encoded here is that CARE answers what the store HAS and SELL helps a shopper CHOOSE; that split is a judgement made when the declarations were written, and **it is not decided in any ADR**."*

### What was measured, 2026-09-05, and what it stopped

A change was proposed and **not made**: narrow CARE's `handles`, whose last sentence — *"Also general questions about what the store sells"* — is the vague clause that lets it win a `recommend`-shaped question. A diagnostic on 2026-09-01 had shown that removing it flips the failing case to `sell` at 0.9.

**The dispatch suite was run on a cloud model first, before touching anything. It scores 1.00.**

| role map | ROUTER model | runs | dispatch accuracy | matrix |
|:--|:--|--:|:--|:--|
| `ollama-dev` | `llama3.2:3b` | 3 | **0.94, 0.94, 0.94** | `care→care` 10/10 · `sell→sell` **5/6** · `sell→care` **1** |
| `cloud-prod` | `gemini-3.6-flash` | 3 | **1.00, 1.00, 1.00** | `care→care` 10/10 · `sell→sell` **6/6** |

**`dispatch_open_ended_advice`** — *"What would you recommend for hiking in wet weather?"*, A19's single stable failure — **passes 3 of 3 on the cloud model.** `structured_repair_rate` 0.00 in all three; p50 2459ms, p95 3842ms against ~1.7s p50 locally; cost recorded as `$0` because `LLM_PRICING_JSON` is unset, which is a missing price rather than a free model.

**So the declaration is not the fault.** Changing it would have tuned a manifest against a failure the model serving production does not have — which [A14](../../open-questions.md) already names in as many words: *"tuning a prompt against a fault the current model does not exhibit is the mirror image of the 2026-07-30 mistake."* **Measuring before changing is the only reason that edit did not ship.**

**One setup fact belongs in the record.** Until 2026-09-05 `.env` pointed every `CLOUD_*` role at **OpenRouter free** and set no `CLOUD_MODEL_EMBEDDER`; Gemini was configured for the first time that day. **There is therefore no earlier cloud dispatch measurement**, and any document implying one is describing an intention.

## Decision

### 1. The rule, stated

> **CARE answers what the store *has*. SELL helps the shopper *choose*.**

| the shopper is asking | agent |
|:--|:--|
| *Do you sell jackets?* · *Is the field jacket in stock?* · *Do you have it in navy?* | **CARE** — does the store have it |
| *Which is warmer?* · *What would you recommend for hiking?* · *I need something for winter under 150* | **SELL** — which one should I buy |
| *Where is my order?* · *What is your returns policy?* | **CARE** — not a product question at all |

This is the rule `dispatch.yaml` was written against. It is now decided rather than assumed, so that a model change which violates it fails against a **written** expectation instead of a habit.

### 2. No declaration and no prompt is changed

`AgentManifest.handles` for both agents stays exactly as it is, including CARE's *"Also general questions about what the store sells"*.

**The measurement is the whole argument.** On the model that serves production the rule is already followed, 3 of 3. An edit here would move a number that is already 1.00, against a fault only one model exhibits.

**Recorded for whoever revisits this:** the vague clause is a known weakness, the diagnostic that identifies it is in A19, and if a future ROUTER model breaks §1 then narrowing that sentence is the first thing to try. The cost of doing so is lower than A19 estimates — `handles` and `handles_examples` are read **only** by `neura-dispatch`, and `chooser.py` returns without a model call when a shop has one agent, so a single-agent shop never reads the declaration at all.

### 3. The release gate is on the expensive direction, and it is zero

**A misroute that sends a question to an agent which answers it by fetching a human must not happen.** Against this dataset that is `care → sell`: SELL's `needs_person` covers orders, delivery, returns, refunds and store policy, so those ten cases are what the dataset calls **DETERMINED** — there is no reading of either agent's design under which SELL is the right choice.

**Gate: zero such misroutes. One is a release failure.**

It is defensible precisely because it is not fitted to a result: it is 0 on **both** models measured, it is the direction that costs the merchant money, and its cases are the ones with no product judgement in them.

### 4. The cheap direction is reported and **not** gated

`sell → care` costs the shopper the product cards ([ADR-0030](0030-a-product-card-is-data-the-widget-draws.md)) and nothing else — CARE answers the question. It is 1 on `ollama-dev` and 0 on `cloud-prod`.

**Gating it now would settle §1 by picking a number**, and would fail the sovereign tier for a defect that costs a card. It is reported beside the rate, as `dispatch.yaml` already insists.

### 5. Flat `dispatch_accuracy` stays ungated

`THRESHOLDS` does not contain it and a unit test asserts that it does not. **That stays true**, and this ADR is the reason rather than an accident: one rate reports a lost card and a summoned human identically, which is exactly what §3 and §4 exist to separate.

### 6. The harness still must not know which direction is expensive

`dispatch_matrix` is built *"without the harness knowing which agents exist or which way is expensive"*. That constraint is Rule 1's shape and this ADR does not weaken it.

**So the severity is declared by the dataset, not inferred by the runner.** The cases whose misroute costs a human carry a tag — `EvalCase.tags` already exists, so this needs no schema change — and the gate counts failures among tagged cases. The runner learns *"this case's miss is expensive"* from the dataset author, never `care` or `sell`.

## What this deliberately does not do

- **It does not change any agent's behaviour.** No manifest, no prompt, no graph.
- **It does not claim dispatch is good.** All sixteen cases are invented and the report says so in a box. 1.00 means the models agree with sixteen questions their author wrote; it is not validation, and [E1](../../open-questions.md) is untouched.
- **It does not resolve A19's sovereign-tier half.** `ollama-dev` still misroutes that one case, and `sovereign` is `ollama-dev` pointed at a customer's host. Like [A20](../../open-questions.md), this is now a **model-selection** criterion for that tier rather than a design fault — [ADR-0018](0018-guard-model-must-refuse.md)'s argument applied to ROUTER.
- **It does not set a threshold for `sell → care`.**

## Consequences

**ADR-0031 becomes shippable.** It required a gate before release; §3 is that gate, and it is met on both measured models.

**A19 changes shape rather than closing.** The product rule is decided (§1). What remains is that a small ROUTER breaks it, which is a tier question and not an overlap question.

**Costs, accepted.**

- **The gate needs a small piece of work** — tagging the determined cases and counting failures among them. It is not free, and §6 is why it cannot simply read the matrix.
- **A gate of zero on ten cases is a weak gate.** Ten invented questions passing is thin evidence; the gate's value is catching a collapse, not proving quality.
- **The rule in §1 is written from two agents.** A third agent that also touches products would need it restated, not extended by analogy.
