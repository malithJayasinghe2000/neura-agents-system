# ADR-0016 — Nothing the Model Wrote Reaches a Shopper Before `verify` Has Passed

**Status:** Accepted · **Date:** 2026-08-03 · **Resolves:** open question A1

## Context

[api-design.md §8](../api-design.md) specifies a WebSocket that streams `token` deltas.
[agent-runtime.md §9.1](../agent-runtime.md) raises the problem with that and leaves it open as
**A1**: `verify` runs *after* `compose`, so a fully streamed answer can be retracted mid-sentence.
Two options were written down — stream only after verify (slower first token), or stream with a
fast pre-check — and the note said "decide before the widget ships". The widget is 1.16 and the
transport is 1.14, so the decision lands here.

It matters more in this system than it would in most, because of what `verify` is for. CARE's
whole safety argument for *answering* rather than escalating is that a draft is checked against
the evidence before it is sent. The class of failure it exists to catch is the confident wrong
answer (open question A9): a fluent paragraph that quotes a domestic delivery price for an
international order, or offers a prepaid return label the system cannot produce. Those failures
read perfectly until you check them.

A retraction is not a neutral cost, either. "Actually, let me connect you to someone" arriving
after two sentences of a wrong answer does not undo the two sentences — the shopper has read
them, a screenshot may exist, and the merchant is the one holding the consequence.

## Decision

### 1. No model-generated text is sent to a client before `verify` passes

The WebSocket streams the *turn*, not the *draft*. Server → client frames:

| Frame | When | Carries |
|:--|:--|:--|
| `accepted` | the turn has started | `conversation_id` |
| `step` | a node finished | the node name — `guard`, `route`, `retrieve`, … |
| `tool_call` | a tool ran | the tool name only |
| `token` | **after `verify` has passed** | successive slices of the final reply |
| `done` | end of turn | `state`, `escalated`, `citations`, `message_id`, `ai_disclosure` |
| `error` | failure | the same error object REST returns |

`step` and `tool_call` are emitted from the graph's own per-node stream, so they
arrive when a node *completes* rather than when it begins. That is a weaker signal
than a true progress bar and it is what the graph can honestly report: a node's
name is a fact once it has run, and inventing "now entering compose" from a
predicted edge would be reporting an intention as an event.

`token` frames carry the verified reply, chunked. The client renders them the way it would render
model deltas, so the *perceived* behaviour — text appearing progressively — is unchanged. What
changed is that every character in that stream is text `verify` accepted.

A blocked or escalated turn emits no `token` frame at all. Its reply is fixed text, delivered
whole in `done`.

### 2. `step` and `tool_call` frames are the latency answer, not a faster verifier

The cost of this decision is time to first token: a shopper waits for compose *and* verify instead
of compose alone. The mitigation is to stream what is *true* during that wait rather than what is
merely early. "Checking your order…" is exactly as informative as the first eight words of a draft
and cannot be wrong in a way that matters.

`step` frames name the node and nothing else. They are already in the state, they are already
logged, and they carry no shopper data, no tool arguments and no model output.

### 3. The "fast pre-check" option is rejected

A cheap classifier that lets streaming start early is a second verifier — a weaker one, sitting in
front of the real one, deciding what a shopper sees. Three reasons not to:

- **The project has measured that one verifier is already unstable.** A8 recorded `verify`
  flipping 0/30 → 30/30 refusals on the same draft when a meaningless second evidence block was
  added. Adding a second, deliberately weaker judgement in front of it multiplies that problem
  rather than routing around it.
- **It would need a threshold**, and [ADR-0011](0011-deterministic-guard-not-classifier.md)
  already declined to pick one for the guard, for reasons that apply unchanged here: there is no
  labelled corpus, no design partner, and no real traffic to calibrate against.
- **It moves the safety boundary into the transport.** The REST and WebSocket paths would then
  apply different checks to the same turn, which is exactly the "the transport is never allowed to
  become a second code path" clause in api-design.md §8.

### 4. The graph is unchanged, and both transports execute it identically

No node, prompt, tool or edge changes; `neura_agent_core.graph` does not learn that a socket
exists. The progress frames come from LangGraph's own per-node stream, which the agent runner uses
**whether or not anyone is listening** — a turn served over REST streams into a discarded callback
and a turn served over WebSocket streams into a socket. Same call, same nodes, same order.

That "whether or not anyone is listening" is deliberate and is the difference between this and a
plausible alternative that would have been wrong: invoking one way for REST and streaming for
WebSocket would create exactly the second code path api-design.md §8 forbids, and the golden suite
would then be evidence about REST only.

## Consequences

**Good**

- The strongest property CARE has — that an answer was checked against its evidence before it was
  sent — survives contact with the transport. It is not weakened by the channel a merchant happens
  to integrate over.
- There is no retraction path to design, test, or explain to an integrator. A sentence that has
  been sent is a sentence that passed.
- REST and WebSocket produce identical outcomes for identical input, so the golden suite measures
  both, and a bug can never be "only over WebSocket".
- `step` and `tool_call` frames turn out to be the feature integrators ask for anyway: a widget
  wants to show "looking up your order" more than it wants eight early words.

**Bad / accepted**

- **Time to first token is worse, and by a real amount.** The shopper waits for the verifier's
  call as well as the composer's. On the local role map that is seconds, not milliseconds. This is
  the price and it is the point; if it becomes intolerable, the answer is a faster verifier model
  or a cheaper check — not showing unverified text.
- **The stream is a simulation.** `token` frames are slices of a finished string, not model
  deltas. Stated plainly here and in the API docs rather than left for an integrator to discover
  from timing, because a client that assumes real deltas may assume things about backpressure and
  partial-word boundaries that are not true.
- **A long turn looks idle between `tool_call` and `token`.** `compose` and `verify` together are
  the longest silent stretch in the turn. `step` frames mark the boundary, but there is nothing
  meaningful to send during composition, and inventing filler would be inventing progress.

## Alternatives considered

- **Stream the draft, retract on failure.** Rejected above. It also makes `verify` cosmetic for
  the streaming transport: the shopper has read the ungrounded sentence, so the check no longer
  protects them, only the transcript.
- **Stream the draft but hold the last sentence back.** A common trick, and it fails against the
  failure mode that matters — the wrong claim is usually in the *first* sentence ("your order
  shipped on the 22nd"), not the last.
- **Buffer the draft client-side and reveal on `done`.** Equivalent to this decision, but the
  unverified text has already crossed the network into a browser where anyone can read it from the
  socket. If the text must not be shown, it must not be sent.
- **Two verifier passes — a fast one to release the prefix, the real one for the rest.** The
  pre-check objection, with extra machinery.
