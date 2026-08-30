# ADR-0031 — The Shopper Never Chooses The Agent

**Status:** Accepted — **design only, nothing is built** · **Date:** 2026-08-30 · **Builds on:** [ADR-0019](0019-widget-is-one-file.md), [ADR-0028](0028-only-the-catalogue-may-say-what-a-store-sells.md) · **Answers:** [A13](../../open-questions.md)

## Context

The product claim is five agents, each a service we run around the clock, bought separately. **A shop that buys two of them can only be delivered one.** Found by hand on 2026-08-30, Stage 8 of the testing log, and written up in **[A13](../../open-questions.md)**.

Three facts, none of which were written down before that day:

**The agent is fixed in the merchant's HTML.** `data-neura-agent`, defaulting to `care`. One word in a `<script>` tag decides what every shopper may ask, permanently.

**Two chat boxes are not a workaround.** `mount()` in `widget.js` returns early if a `neura-chat` element already exists, so pasting the snippet twice makes the second widget **silently do nothing** — no error, no box. Both would also draw at `position:fixed; right:20px; bottom:20px` and overlap.

**CARE is the wider agent, so buying SELL as well currently buys a *narrowing*.** CARE's `product_qa` covers *"availability, price, sizes, materials, stock, comparisons, recommendations"*; SELL's `needs_person` covers *"existing orders, delivery status, returns, refunds, exchanges… store policy"* — all sent to a person. A merchant owning both is better off pointing the box at CARE and never using SELL: they lose the product cards ([ADR-0030](0030-a-product-card-is-data-the-widget-draws.md)) and keep everything else.

**So the shopper is made to classify their own question**, against a boundary that exists for our packaging and billing and that they cannot see. `enabled_agents` grants permission and changes nothing a shopper experiences.

### The constraint that shapes the whole design

**Nothing in `neura-api` knows the word "care" or "sell".** `routes/agent.py` says it in its own docstring: *"`/v1/care/chat` exists because CARE's manifest says `route_prefix="/v1/care"`, not because anything here knows the word 'care'."* Agents self-register through the `neura.agents` entry point group.

A dispatcher containing `if the question is about products → use sell` would put agent names in shared code — the same failure as a platform name outside `neura-adapters` (rule 1). **So the agents must declare what they handle, and the dispatcher must read declarations rather than know names.**

## Decision

**A shopper's message arrives without an agent, and the server decides which of the merchant's enabled agents answers it.**

### 1. A new front door

`POST /v1/chat` — no agent in the path. The widget posts here and **stops sending `data-neura-agent`**.

The existing `/v1/{agent}/chat` routes **stay**. They are an agent's own manifest-declared prefix, they are what integrators and the eval harness address, and a single-agent embed has nothing to dispatch. This adds a door; it closes none.

### 2. An agent declares what it handles

A new field on `AgentManifest` — which is `frozen` and `extra="forbid"`, so this is a deliberate schema change and every agent must declare or be invisible to dispatch.

**The shape is one plain sentence plus three to five real example questions.** Not a list of intent names: an intent vocabulary belongs to each agent's own `route` prompt, the dispatcher does not own it, and two agents claiming an overlapping intent would have no tie-break. Not a description alone either — CARE and SELL both reduce to *"helps shoppers"* in one sentence, and they are exactly the pair that must be told apart.

**This field is the dispatcher's prompt.** That is the reason for the shape: a wrong dispatch is diagnosed by reading a manifest, and a new agent is made reachable by writing five sentences rather than by editing shared code.

The dispatcher reads those declarations. It never contains an agent key.

### 3. One small model call chooses — and only when there is a choice

**If the tenant has one agent enabled, no call is made.** There is nothing to choose, and a CARE-only shop behaves exactly as it does today: no new latency, no new cost, no new failure mode.

With two or more enabled, **one small model call** picks, before the agent's own graph runs.

**The cost is stated rather than hidden: that is a second classification on every dispatched turn**, since each agent's own `route` node classifies again. A deterministic shape rule was considered — [ADR-0028](0028-only-the-catalogue-may-say-what-a-store-sells.md) is precedent for one — and rejected here: ADR-0028's rule reads the *shape* of a question and deliberately never the subject, and choosing between agents **is** a judgement about the subject. A rule that tried it would be the "regex that guesses" that ADR-0028 removed from `route`, one layer higher.

### 4. A question for an agent the shop has not bought goes to a person

Shop has SELL only; shopper asks *"where is my order?"*. `Tenant.may_use()` already answers *"has this tenant bought this agent?"*, and the answer is no.

**The turn is handed to a human.** Not declined, and **not** answered by the unbought agent.

The cost is real and is accepted: the merchant pays a person for a question a service they did not buy could have answered. The alternative — quietly running CARE for a shop that has not bought CARE — bills nobody for work we did, and makes `enabled_agents` a suggestion rather than an entitlement.

### 5. One conversation, marked per message

A conversation that moves from SELL to CARE stays **one** conversation in the merchant's console, with **each message marked with the agent that produced it**.

The merchant reads the thread the way the shopper experienced it. Two threads would be half a story told twice, and would hide the handover — which is the part most worth reading while this is new.

Needs a column on `conversation_messages`.

### 6. The dispatcher is graded by a target that is not an agent

**Rule 4 has nowhere to stand today, and this is the part that must be built before the dispatcher merges.** Every golden dataset in this repository lives *inside* an agent package and is discovered through the `neura.eval_targets` entry point — one target per installed agent. The dispatcher belongs to no agent, so there is no shelf to put its dataset on.

**`neura-evals` gains the idea of a target that is not an agent**, with its own dataset directory. The alternatives were weighed and rejected: a standalone probe — like `scripts/router_probe.py`, which already exists for exactly this kind of question — cannot hold a release gate, because it does not run in `make check`; and splitting the dataset across the agents it routes to gives the case that matters most, *a question **both** agents could plausibly take*, no obvious home.

The honest reason for the larger option: the guard and the dispatcher are both **shared** machinery, and shared machinery currently has nowhere to be measured at all.

### 7. It dispatches on the `ROUTER` role, and that choice is revisited with numbers

Not a new `DISPATCHER` role, and not yet a commitment to `ROUTER` forever.

`ROUTER` is the role built for *"classify this message"*, and it is filled in **every** role map, so this adds no configuration. A new role would have to be filled in four maps and becomes one more setting that breaks a map silently when unset — which is not hypothetical: **`CLOUD_MODEL_EMBEDDER` is unset today, and that alone is why `cloud-prod` cannot serve a widget turn.**

**The cost is named rather than assumed.** Dispatch runs *before* the agent's own `route`, so a dispatched turn carries two classifications. [A11](../../open-questions.md) measured the configured cloud ROUTER at a **7.7s median** on routing-shaped work; if that holds here, it is added to every turn in a two-agent shop.

**So latency is measured on §6's dataset run rather than estimated** — it comes off that run for free, and if `ROUTER` proves too slow, adding a `DISPATCHER` role afterwards is an edit to a dictionary. This follows [ADR-0006](0006-llm-model-roles.md)'s standing principle: a model choice here is made by eval results at swap time, never in advance.

**The failure mode to guard against is *"we will measure it later"*, and then not.** The measurement is part of the build, not a follow-up.

## Consequences

**A misroute is asymmetric, and that is what to measure.** A shopping question sent to CARE is answered — CARE's `product_qa` covers recommendations, so the shopper loses the product card and nothing else. An order question sent to SELL reaches a **person**. The failure directions are not equally expensive and a single accuracy number will hide that.

**Rule 4 applies and is not optional.** Dispatch accuracy needs its own metric, its own dataset and its own gate before this merges. There is no such dataset today.

**The hard rule is not breached.** `AGENTS.md` forbids an agent importing another agent. A layer *above* both is not one importing the other — CARE and SELL still do not know each other exists. **This was checked before the option was offered**, because it is the reason the obvious design looks blocked and is not.

**Every future agent must declare, or it cannot be dispatched to.** That is the intended pressure: a manifest that does not say what it handles is an agent nobody can reach.

**The widget changes.** It stops choosing. `data-neura-agent` remains meaningful for a single-agent embed and for integrators, so the attribute is not removed.

## What this does not decide

**Scope stays [blueprint-v2](../../business/blueprint-v2.md).** Reviewed against `docs/archive/FiveNeurals_AI_Agents_Blueprint_v1.md` in the same session, at the owner's request. v1's larger SELL features — predictive lead scoring, dynamic pricing, autonomous cart recovery, revenue forecasting — are **not re-opened here**, and each needs its own ADR. Two carry a further cost worth naming now: **dynamic pricing is a write** and needs a superseding ADR for [ADR-0010](0010-read-only-mvp-tools.md); **cart recovery** is recorded in `CLAUDE.md` §2 as excluded and not re-openable, so re-opening it is an explicit reversal, not an extension.

**Nothing about non-chat surfaces.** Lead scoring watches behaviour and has no question to route; the MCP server and the product feed have no chat at all. `CLAUDE.md` §5 already establishes that **SELL is one product with three surfaces and only one is an agent** — this ADR governs that one surface and no other.

**Not the greeting.** *"hi"* currently routes `out_of_scope` and gets the canned decline, which is the first thing every shopper sees. Its own question, not this one.

**Not whether the shopper is told the service changed mid-conversation**, and not the wording of CARE's and SELL's own declarations — the *shape* is fixed by §2; what each of them actually says is written when they are written.
