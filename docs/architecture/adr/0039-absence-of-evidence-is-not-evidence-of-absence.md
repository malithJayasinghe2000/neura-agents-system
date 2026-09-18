# ADR-0039 — Absence Of Evidence Is Not Evidence Of Absence

**Status:** **Accepted** — owner decision, 2026-09-18 · **Date:** 2026-09-18 · **Extends:** [ADR-0018](0018-guard-model-must-refuse.md) · **Supersedes:** nothing · **Resolves:** the undecided half of [S9](../../open-questions.md) · **Bears on:** [A9](../../open-questions.md), [A22](../../open-questions.md), [A23](../../open-questions.md), [S6](../../open-questions.md), [S8](../../open-questions.md), [ADR-0025](0025-verify-sees-only-what-the-draft-cites.md)

## Context

`scripts/verify_probe.py`'s arm **E** holds a comparative draft about two jackets. Its last factual clause is:

> *"…the Fell packs into its own pocket and **the Crag does not**."*

The evidence block says of the Fell *"Packs into its own pocket"*, and of the Crag only that it is *"**Heavier than a packable shell** and cut for movement"*. **Nothing anywhere states that the Crag does not pack.** The draft inferred an absence from a comparison and stated it to a shopper as a fact about a product.

Arm E's expectation has always been `expect_grounded=True`, and the arm's own comment enumerates the facts it means to check — two prices, two hydrostatic heads, two constructions. **The packing clause is not among them.** It entered the arm without being accounted for, and four arms (E, F, G, H) reuse that draft.

### It was measured twice, fourteen months apart in effort and three weeks apart in time

**2026-08-27**, chasing [S9](../../open-questions.md): `make verify-probe AGENT=sell` on `gemini-3.6-flash`, n=10 per arm. The four discrimination gates were perfect — A and B grounded 10/10, C and D catching both fabrications 10/10 — and **arm E was refused 10/10, arm G 10/10, arm F 8/10**. Every refusal named the same clause. The finding was written down honestly and **left undecided**:

> That makes arm E's `expect grounded` a claim about what `verify` **SHOULD** accept, not a fact about the model — and it is undecided… Whoever answers this answers S9, S6, S8, A9 and ADR-0025 together, and it is a design decision, not a tuning one.

**2026-09-18**, chasing [Finding 37/A22](../../TESTING_LOG.md) from the other direction: the same probe on `gemini-3.5-flash`, n=3, prompt unchanged, **30 calls answered and zero errors**. Arms E, G and H refused 3/3 — **quoting the identical fragment** — while `llama3.1:8b` accepts it 10/10.

Two cloud models, two occasions, one clause. **This is not model noise; it is a disagreement about what "grounded" means**, and it was found a second time only because nobody had answered it the first time.

### Why it is the same disease as A22, wearing the opposite sign

| the draft invents… | example | `llama3.1:8b` | cloud verifier |
|:--|:--|:--:|:--:|
| a **positive** fact about a product | *"1311 is waterproof with taped seams"* ([A22](../../open-questions.md), arm I) | allows it **10/10** ✘ | refuses **3/3** ✔ |
| a **negative** fact about a product | *"the Crag does not [pack]"* (arm E) | allows it **10/10** | refuses **3/3** |

Both rows are one behaviour: **stating something about a product that the merchant's own text does not state.** The production verifier permits both; the candidate refuses both. Read this way the cloud model is not being fussy — it is being *consistent*, and arm E's expectation is what disagrees with it.

## Decision

> **A claim a draft makes about a product is grounded only if the evidence supports it. Silence is not support — and a negative claim is a claim. If the merchant's text does not say it, the agent may not say it, in either direction.**

Concretely: *"heavier than a packable shell"* does not license *"does not pack"*. A shopper told the Crag will not pack down, who then finds that it does, was misled by us — and the merchant's catalogue never made the claim we were sued over.

**This does not enlarge what `verify` refuses.** It states what `verify.md` already implies and never wrote down. `verify.md`'s **Grounded** examples are all inferences *forward from a stated attribute* (*"waterproof and taped seams, so it should handle wet weather"*). None infers an attribute from the absence of one. The gap was never a rule; it was an unwritten assumption, and two models read it in opposite directions.

### What follows, mechanically

**1. Arm E's expectation is wrong, and so is the scoring of arms F, G and H.** All four reuse the contaminated draft, so all four have been scored against an expectation this decision reverses. The correct answer for that draft is now **refuse**.

**2. Every recorded number for arms E, F, G and H is not comparable across this line.** Including 2026-08-27's. That matters most for [S9](../../open-questions.md), whose entire finding is the differential **E✔/G✔ vs F✘** on `llama3.1:8b` — a differential built on treating E and G as clean baselines when, under this decision, `llama3.1:8b` was **failing** both. **[ADR-0025](0025-verify-sees-only-what-the-draft-cites.md)'s probe evidence must be re-read, and this ADR does not re-read it.**

**3. `llama3.1:8b` fails the corrected arm E.** It accepts the invented negative 10/10 — the same miss as arm I, on the same disease. Under [ADR-0018](0018-guard-model-must-refuse.md)'s rule that a candidate must clear every arm, the current `ollama-dev` `GUARD` binding now fails the bar for **two** independent reasons rather than one.

**4. `verify.md` is not edited.** [Finding 43](../../TESTING_LOG.md) measured what adding a rule to that file does to `llama3.1:8b`: it fixed one arm and broke six, including the guard-rail. A model that already applies this principle needs no sentence telling it to, and a model that cannot hold the principle will not be rescued by one. **This is [ADR-0018](0018-guard-model-must-refuse.md)'s argument and it is unchanged: when the GUARD model cannot discriminate, the answer is the model.**

## What this ADR deliberately does NOT decide

- **Which model holds `GUARD`.** The candidate's evidence is n=3 on ten arms, plus n=10 on a different model three weeks ago. That is a screen, not a qualification. ADR-0018's bar is every arm, and it must be re-run against the corrected expectations.
- **Arm F.** On `gemini-3.5-flash` arm F **accepted** the contaminated draft 3/3 while its own controls refused it — so under this decision F is a **missed fabrication**, and the only arm the candidate fails. On `gemini-3.6-flash` F was 8/10 refused where E and G were 10/10. **Arm F moves on evidence that carries no meaning for the claim, on both cloud models**, and that is [A8](../../open-questions.md)'s instability, unexplained and unresolved here.
- **Whether the probe's repair is to flip arm E's expectation or to split it** into a clean comparative arm plus a new inference-from-silence arm. Deleting the clause was attempted on 2026-09-18 and reverted before measurement: it makes the disagreement unexpressible, which is [A24](../../open-questions.md)'s own lesson — *"every future arm should be asked what its fixture makes impossible to say"*.
- **S6, S8 and ADR-0025's re-reading.** S9 said answering this answers those together. It unblocks them; it does not perform them.

## Consequences

**Good.** A three-week-old undecided question is decided, and the decision is written where the next session will find it rather than rediscovered a third time. The A22 repair path is no longer blocked on an unanswered design question. The two failures now have one name, which makes them one fix.

**Bad, and it is a real cost.** A body of recorded probe numbers loses its meaning, S9's differential most of all, and re-establishing it costs runs nobody has budgeted. **The corrected bar is harder than the old one**, so `make verify-probe AGENT=sell` stays red — now for arms E and I rather than arm I alone — and it must stay red until a model clears both.

**Accepted risk.** This was decided from two probe fixtures and one clause, not from merchant data or a shopper complaint. It is a judgement about what an assistant may say, and it is the owner's to make; it is recorded here so that a future session disagreeing with it writes a superseding ADR rather than quietly restoring `expect_grounded=True`.
