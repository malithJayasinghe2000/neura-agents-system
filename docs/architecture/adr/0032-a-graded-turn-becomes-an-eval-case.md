# ADR-0032 — A Graded Turn Becomes An Eval Case

**Status:** Accepted — **design only, nothing is built** · **Date:** 2026-09-03, accepted 2026-09-05 after owner review · **Builds on:** [ADR-0020](0020-a-withheld-turn-says-so.md), [ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md) · **Answers:** [E1](../../open-questions.md) in part

## Context

**The loop was designed, written down three times, surfaced to a user, and never built.**

- [agent-runtime.md §6](../agent-runtime.md) — *"Graded shadow conversations feed the golden dataset, so the review effort compounds instead of evaporating."*
- [evaluation-strategy.md §2](../evaluation-strategy.md) — *"Graded shadow-mode conversations flow back in, so review effort compounds."*
- The console's Review screen — *"your verdicts… become the examples it is tested against."* **Deleted 2026-09-03**, because it was the only one of the three making the promise to a *user*.

`ShadowVerdict` appears in five places: the table, the write route, the read route, its unit test, and nowhere else. **No code under any `evals/` directory reads `shadow_turns`.** All eleven datasets are hand-written YAML, every case marked `synthetic: true`.

### What already exists, and it is most of it

This is the finding that sizes the work. The **receiving** end was built in full and has been waiting:

| already built | where |
|:--|:--|
| `EvalCase.synthetic`, defaulting to `False` — *"Invented rather than taken from a real conversation. NEVER counted as validation."* | `evals/dataset.py` |
| `Dataset.synthetic_count`, `is_fully_synthetic` | `evals/dataset.py` |
| `RunReport.is_validation` — *"A run over synthetic cases proves the harness works, not the agent."* | `evals/runner.py` |
| The report banner — *"Every case in this run is synthetic… Replace with real conversations before treating any score as validation."* | `evals/report.py` |
| Per-run and per-case `synthetic` counts in the persisted run file | `evals/persist.py` |
| `load_all()` globs `*.yaml`, so a new dataset file is discovered with no registration | `evals/dataset.py` |

**The moment one real case lands, `is_validation` flips and that banner stops printing.** Nothing else has to change to receive this.

### And the producing end is nearly complete too

A graded turn already carries almost every field an `EvalCase` needs. Measured against the eight turns graded on 2026-09-03:

| `EvalCase` field | source | present |
|:--|:--|:--|
| `input` | `conversation_messages.content` via `shadow_turns.message_id` | ✅ |
| `intent` / `expect.intent` | `shadow_turns.intent` | ✅ |
| `expect.tools_called` | `shadow_turns.tools` | ✅ |
| `expect.grounded` | `shadow_turns.grounded` | ✅ |
| `expect.escalated` | `shadow_turns.escalated` | ✅ |
| `synthetic: false` | implied by the row existing | ✅ |
| `expect.must_contain` | — | ❌ **nothing decides this** |

**So the gap is one step and one judgement.** The step is promotion. The judgement is which facts must survive a rewording.

### Why `must_contain` cannot be derived

A grade says *this reply was good*. It does not say *what made it good*. Re-run the same question and the agent will not repeat itself:

> graded and approved: *"Our standard return policy allows you to return most items within **30 days** of delivery."*
> a later, equally correct reply: *"You can return items up to **30 days** after they arrive."*

Nothing mechanical separates the part that must survive (`30 days`) from the part that may change (everything else). A test that compares whole replies fails on correct answers; a test that compares nothing passes an agent that has started saying **45 days**. **The second failure is the one this project already names as the quiet, expensive one** ([policy_qa.yaml](../../../agents/care/src/neura_agent_care/evals/datasets/policy_qa.yaml): *"the shopper finds out at the point of return, and by then it is the merchant explaining a promise they never made"*).

## Decision

### 1. Promotion is explicit, and a human performs it

A verdict does not become a case by being saved. **A second, separate action promotes it**, and the promoting human supplies what the grade cannot.

The reason is Rule 4. *"Nothing merges without an eval"* means that once graded turns reach the suite, **a verdict can decide whether code merges**. A misclick would then become a permanent assertion that no one remembers making. Grading is cheap and reversible; promotion is neither.

### 2. A promoted case is an ordinary `EvalCase` with `synthetic: false`

No new schema, no parallel format, no second runner. It is the same object the hand-written cases use, and it earns its authority from one field the framework already honours.

### 3. Promoted cases live in their own dataset file

`datasets/graded.yaml`, one per agent, alongside the invented ones. `load_all()` picks it up with no registration.

**Not merged into the existing intent files.** Two reasons. A reader of `policy_qa.yaml` can currently trust its header — *"ALL CASES ARE SYNTHETIC"* — and mixing would silently make every such header a lie. And the invented files are organised by intent because a human grouped them that way; promoted cases arrive in the order shoppers happened to ask, which is not a grouping and should not pretend to be one.

### 4. The human supplies the facts, at promotion time

The promoting human marks which spans of the approved draft must survive. Those become `must_contain`. **Nothing is auto-extracted.**

Auto-extraction was considered and rejected: pulling every number and proper noun out of the approved reply would pin words the agent may fairly reword, producing failures that are not defects. This repository records, twice, a change made to turn a number green. **A suite that fails for no reason is an invitation to make exactly that change a third time.**

Marking nothing is permitted, and produces a behaviour-only case. That is weaker, and it is honest about being weaker.

### 5. Each verdict promotes differently, and one of them does not promote at all

| verdict | becomes | why |
|:--|:--|:--|
| `agree` | a case asserting route, tools, `grounded`, `escalated`, plus the marked facts | the reply was right; these are the parts that must stay right |
| `would_have_harmed` | a case, **after an explicit confirmation, and the turn stays flagged until answered** (§13) | the strongest signal in the system, and the one worth the most as a permanent test |
| `disagree` | **nothing, by default** | see below |

**A `disagree` records that a reply was wrong. It does not record what right would have been**, and a test needs the second. Turning *"this was bad"* into `must_not_contain: [the bad phrase]` is available and is deliberately **not** automatic: it asserts that one wording is forbidden, which is a much narrower claim than the grade made, and a suite full of narrow negative assertions is the shape of the 2026-07-30 benchmark that scored a more-suspicious agent well *by construction*.

A `disagree` may be promoted **only** by a human writing the expectation by hand. The default is that it stays a grade — evidence for the merchant, not a test.

### 6. A promoted case records where it came from

`tags` carries the source `shadow_turns.id` and the promoting user, so any assertion can be traced to the turn and the person behind it. *"Who approved this?"* is already the question `reviewed_by` exists to answer; a case that outlives the memory of its promotion needs the same.

### 7. Real and synthetic scores are reported apart, never folded

The runner already counts both. The report must show them separately, and **release gates continue to be computed as they are today until a gate over real cases is set deliberately.**

Otherwise eight real cases entering a fourteen-case suite move every rate in it, and the movement would be read as the agent changing when only the question set did. That is [Finding 19](../../TESTING_LOG.md)'s near-miss in a new place: a number that moved for a reason nobody checked.

### 8. Anyone who may grade may promote — and that is a limitation, not a choice

`memberships.role` **exists with exactly one value, `owner`** ([identity/schema.py](../../../packages/neura-core/src/neura_core/identity/schema.py), ADR-0026 §5). There is no permission system and nothing to approve *to*, so "a second person signs off" cannot be built today and is not designed here.

**Recorded for when a second role arrives:** promotion should then be **owner-only** even if grading is not. Grading is cheap, reversible and is the merchant's own evidence; promotion writes an assertion that can block a merge. The two do not deserve the same bar.

### 9. A promoted case is edited and deleted **in the file**, and there is no disable flag

Cases are YAML in the repository. Editing one is a commit; deleting one is a commit. **The console does not edit or delete cases.**

**Why not from the console:** a test that can be changed quietly from a web page is a test nobody can trust. In git every change is a diff with a name and a message on it, which is the same argument `reviewed_by` already makes about grading.

**And there is deliberately no `enabled: false`.** A switch that silences a failing case is how a suite rots — it is turned off "for now" by someone who means to come back. Deletion is not lossy here: git keeps the case, and the commit message keeps the reason, which is a better record than a flag nobody has to justify.

### 10. One graded turn promotes at most once

Promotion refuses a turn whose `shadow_turns.id` already appears in a dataset. §6 records that id on every promoted case, so the check reads what is already there.

**Why it matters more than it looks:** a duplicate is not a harmless extra row. The same question would be counted twice in every rate the suite reports, tilting each one toward whatever happened to be promoted twice — a number moving for a reason nobody checked, which is [Finding 19](../../TESTING_LOG.md)'s failure in a new place.

### 11. Facts are marked by **highlighting the approved draft**, never typed

The promotion UI lets the human select spans of the reply they approved. It does **not** accept free text.

**This is a safety property, not a convenience.** A free-text box lets a human enter a fact the agent never said — and the case then asserts an expectation nobody ever verified, wearing the authority of `synthetic: false`. Highlighting guarantees every `must_contain` string came out of the exact reply a human read and approved.

Selecting nothing remains valid (§4) and yields a behaviour-only case.

### 12. A policy change makes its case fail, and that is the design

A merchant who moves their returns window from 30 days to 45 makes every promoted case asserting `"30 days"` **wrong**: the agent reads the new policy, answers correctly, and the case fails.

**Nothing detects this, and the failure is the mechanism.** A human investigates, sees the policy moved, and deletes or edits the case (§9).

**The accepted cost, stated plainly:** that failure is indistinguishable from a regression until someone opens it. At the current scale — one shop, few cases — reading it is cheap, and a policy change *should* force a review of what was asserted about it. It gets worse as cases accumulate.

**The better answer is recorded and not built:** store a fingerprint of the source document with the case and mark the case *stale* when the source moves, before it ever fails. `synced_entities.fingerprint` exists, but the policies these cases assert about arrive through tools rather than that table, and **whether they carry a stable fingerprint has not been verified.** That check is a precondition, not a detail.

### 13. `would_have_harmed` is confirmed by a human, and cannot be left in silence

**No auto-promotion.** A misclick would otherwise become a permanent assertion that a good reply is bad — failing forever, blocking merges under Rule 4, for a reason nobody remembers making.

**And a confirmation dialog alone is not enough**, because it is answered by reflex and then forgotten. A `would_have_harmed` turn stays flagged in the queue until the human takes one of exactly two actions:

- **promote it** — it becomes a permanent case, or
- **skip it, with a reason** — *"misclick, this reply was fine"*, recorded like a grade.

**Silence is not one of the options.** The verdict that means a customer would have been hurt is the one that must not be scrollable past.

## What this deliberately does not do

- **It does not train anything.** No grade changes any model, prompt or weight. The agent does not improve because a human approved it; a human still fixes what a grade exposes. Shadow mode is an exam, not a lesson.
- **It does not set a go-live threshold.** *How many `agree` verdicts mean it is safe to launch* is not decided here and no number for it exists anywhere in this repository.
- **It does not change shadow mode, the console's grading screen, or any agent graph.**
- **It does not re-open Rule 4.** The release gate keeps its current inputs (§7).
- **It does not make the eight turns of 2026-09-03 a measurement.** They are one shop, one model, and every question was typed by the person who built the system. They may seed the mechanism; they validate nothing (CLAUDE.md §4).

## Consequences

**Good.** The review effort stops evaporating — the promise made in two architecture documents becomes true. `is_validation` flips on the first promoted case and the synthetic banner stops printing, which is the single most honest signal this project has about its own evidence. Model swaps ([A14](../../open-questions.md)) and the sovereign tier's router question ([A20](../../open-questions.md)) become re-runnable numbers rather than arguments.

**Costs, accepted.**

- **Promotion is manual work**, per turn, forever. It is deliberately not free, because the thing it produces can block a merge.
- **The console needs a new control** — marking spans of a draft — which is real UI work and has no equivalent today.
- **A wrong promotion is durable.** Cases can be edited and deleted like any file, but nothing detects a bad one; it will look exactly like a regression when it fires.

**The one that is not yet solvable, and must be recorded now.**

**A promoted case puts a real shopper's words into this repository.** Today the only "merchant" is the project owner and the only shoppers are him, so nothing turns on it. **It stops being fine the moment a real merchant's traffic is graded** — which is exactly the situation this ADR exists to prepare for. [evaluation-strategy.md §5](../evaluation-strategy.md) already names the neighbouring version of this hazard about judge tiers and *"our own processor commitments"*.

**So: no case from a tenant other than one we own may be promoted until that question is answered.** It is not answered here, it needs [blueprint-v2 §9](../../business/blueprint-v2.md) and probably a superseding ADR, and it is a hard precondition on the design partner ([B2](../../open-questions.md)) this project is otherwise waiting for.

## Settled by owner review, 2026-09-05

Eleven questions were put to this design by the owner. **Nine are now decided and are §§4, 5, 8–13 above** — five of them were holes this ADR was silent on rather than questions it had answered: who may promote (§8), editing and deleting a case (§9), promoting one turn twice (§10), how facts are selected (§11), and what a policy change does (§12).

**One remains open, deliberately.**

### The go-live threshold is not set, and cannot be set yet

*How good must the agent be before a merchant lets it answer real shoppers?* **No number for this exists anywhere in this repository**, and one drawn from the eight owner-typed turns of 2026-09-03 would be a number invented to be met (CLAUDE.md §4).

**Its shape is already argued in the code, and that much is not open.** `shadow.py`, on why `WOULD_HAVE_HARMED` is a separate verdict from `DISAGREE`:

> *"One of these in fifty turns is not '96% agreement', it is a reason not to launch, and averaging it into a single quality number is how that reason disappears."*

So the threshold is **not one number**. It is at least two, and probably three decisions:

1. **A minimum volume** before the question may be asked at all. Three graded turns all marked `agree` is "100%" and means nothing.
2. **An agreement rate.**
3. **A hard bar on `would_have_harmed`**, which is a gate rather than an average — almost certainly zero, and never folded into (2).

**This is blocked on real graded volume, which is blocked on [B2](../../open-questions.md).** It is recorded here so that the absence is deliberate and visible rather than an oversight, and so that nobody sets it by reading a rate off a small suite and rounding down.
