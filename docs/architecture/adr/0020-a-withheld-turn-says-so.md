# ADR-0020 — A Withheld Turn Says So, And The Server Supplies The Words

**Status:** Accepted · **Date:** 2026-08-15 · **Resolves:** open question P8 (4) · **Builds on:** [ADR-0016](0016-stream-only-after-verify.md), milestone 1.15 ([agent-runtime.md §6](../agent-runtime.md))

## Context

Milestone 1.15 made a turn run in full while the shopper is shown nothing. That was the right mechanism and it left a hole exactly one layer up: `reply` is `""` and `state` is `shadowed`, and until 1.16 there was no client to notice.

Three facts about shadow mode decide this question, and all three are already in the tree:

- **The mode is resolved *after* the turn**, because it is per-intent and the intent is something the turn produces (`shadow_intents`, agent-runtime.md §6). A client therefore cannot know in advance that it is about to be told nothing, and cannot be configured out of the problem.
- **A shadowed turn is the only empty reply in the system.** `blocked` and `escalated` both return fixed text from a file. So this is one trigger, not a class — and a fix for it generalises to any future state that withholds.
- **No person has been told.** A shadow turn emits no `conversation.resolved` and no `conversation.escalated` webhook, deliberately (1.15): the merchant is paying for evidence, not being told a colleague was called when nobody was. There is also no console for a human to read the draft in — that is Phase 2.

A widget that renders an empty string renders nothing, and a chat that silently swallows a question is a bug report from the merchant within a day.

## Decision

**A response whose reply is withheld carries the words to say instead, and those words come from the server.**

### 1. A sibling field, not a repurposed `reply`

`fallback_message` is added to the chat response, to the WebSocket `done` frame, and to nothing else. It is non-empty **only** when the turn produced no reply for the shopper.

`reply` stays empty on a shadowed turn. That is 1.15's decision and it is untouched here: the draft is withheld, and `TurnResult.reply` remains the only thing a transport may read. `fallback_message` is not the draft, not a summary of the draft, and not produced by a model — it is fixed text, in the same family as `decline`'s file and the guard's block message, both of which already exist precisely so that a shopper can be answered without a model call.

Consequently **ADR-0016 is not weakened**. Nothing the model wrote reaches a shopper before `verify` passes, because nothing the model wrote reaches the shopper at all.

### 2. It must not claim that a person was told

The tempting default is *"someone from our team will get back to you."* **Nobody will.** No webhook fired, no queue was joined that a human is watching, and no console exists to watch it in.

That sentence is the [A9(3)](../../open-questions.md) failure in a new place: an offer to follow up that nothing can honour. A9(3) was measured, found to be a real defect in composed replies, and the detector for it sits unwired in `guard/promises.py`. Shipping the same failure as a *hardcoded platform string* — in the one message on the path where no verifier runs, because no model ran — would be worse than the case that was caught, not better.

So the platform default states what is true and offers nothing: the shopper is told their message was received and that no automated answer is available, and is pointed at whatever contact route the merchant configured. A merchant who has configured none gets a message that promises nothing rather than a plausible sentence about a team.

### 3. The merchant owns the wording, through config

`TenantConfig.withheld_message` holds it, `None` meaning the platform default — the same shape as every other field there, and the same rule: this field is read by something, or it would not exist.

This is the reason the string belongs on the server and not in `widget.js`. A message in the JavaScript asset is merchant-facing voice that the merchant cannot change, in a file no merchant can see, versioned by a cache header. Every other shopper-facing sentence in this system lives in a content-hashed prompt file or in tenant config, and this one is not the exception.

### 4. The widget renders it as the system speaking, and never renders an empty bubble

`fallback_message` is displayed in a visually distinct system row, not as an assistant message: the assistant did not say it. `ai_disclosure` still renders, because Article 50 is about the interaction being with a machine and not about any particular sentence.

And the invariant that makes this a control rather than a nicety:

> **An empty `reply` with an empty `fallback_message` is a client-side error path — logged and shown as a failure — never silence.**

A widget that has nothing to render must say so. Silence is the one outcome that is indistinguishable from a bug, and it is the outcome a naive implementation defaults to.

## Consequences

**Good**

- The shopper is told something true. The merchant sees a working widget while the agent is being validated, which is the entire premise of running shadow mode on real traffic.
- The wording is a merchant setting, reviewable and changeable without a deploy.
- The invariant is testable on both sides — a server test asserts a withheld turn always carries non-empty text, and a `node --test` case asserts the renderer never emits an empty bubble.

**Bad, or merely accepted**

- The API response grows a field. Every existing client keeps working; a client that ignores it renders the same nothing it would have rendered before, which is why the widget's own test is the one that matters.
- A shopper in a shadowed conversation gets no help. That is what shadow mode *is*, and the honest failure is a visible one.
- The default wording is a guess about tone, like every threshold in this project. It should be revisited with the first design partner (**B2**) and is not a measurement.

## What would change this

`SUGGEST` and `SUPERVISED` (agent-runtime.md §6) both put a human behind the withheld reply. When either ships — both need the Phase 2 console — the message may honestly say a person is looking, and the config field is where that changes. **Not before**, because the sentence is only true when the console it describes exists.
