# ADR-0023 — Agent #2 Is SELL, Read-Only, And Every Protocol Is An Output Format

**Status:** Accepted · **Date:** 2026-08-26 · **Builds on:** [ADR-0003](0003-canonical-domain-model.md), [ADR-0009](0009-generic-commerce-interface.md), [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0021](0021-synced-entities-are-documents.md) · **Design:** [`docs/agents/sell.md`](../../agents/sell.md)

## Context

Phase 1 is complete through milestone 1.16 plus sync persistence and the scheduler. Milestone 1.17 — deploy — was next, and was **deliberately reordered behind this decision** by the project owner on 2026-08-26. The stated reason is go-to-market: one agent is not enough to open a conversation with a merchant, and there is still no design partner (**B2**, the top project risk). Deploy is not cancelled.

[`docs/agents/README.md`](../../agents/README.md) is a stop sign in front of exactly this decision, and it is right: four of the five agents have a product description and **no technical design at all**. It also states the reason the choice was deferred — *which* agent comes second should be decided by what a real merchant asks for, not by us guessing. **There is no merchant to ask.** So the decision is being made on the only evidence available, which is what the codebase can support today without inventing a customer's preferences.

### Two candidates, and why one of them collapsed on inspection

**MIND was the first recommendation, and it was withdrawn on checking.** Its headline capability — natural-language questions over synced data, *"how many orders are stuck in processing?"* — needs a store-wide order query. The adapter protocol has `find_orders_for_customer` and `get_order`, and nothing else for orders. So MIND would require one of:

- every merchant's bridge gaining a new endpoint — breaking the [ADR-0009](0009-generic-commerce-interface.md) adoption argument, which is that the spec is small enough to implement in an afternoon;
- orders being synced wholesale — which [commerce-integration §6.1](../commerce-integration.md) refused on purpose;
- or querying synced documents relationally — which [ADR-0021](0021-synced-entities-are-documents.md) says is a superseding ADR, not a column.

Three doors, all of them expensive, and the cost lands on people who are not us.

**SELL's read-only half needs no adapter change at all.** Verified against the code rather than assumed: `PRODUCT_SEARCH`, `PRODUCT_READ`, `INVENTORY_READ` and `CATEGORY_READ` all exist in `neura_domain.Capability`, and `list_categories` is already on the `CommerceAdapter` protocol. A store conformant for CARE is already conformant for SELL. That asymmetry, not a product opinion, is what decided this.

### The part of SELL that is not available

[Blueprint §5.2](../../business/blueprint-v2.md) scopes SELL as agent-readiness — MCP server, agent-consumable catalogue, **agent-facing checkout** — plus cart recovery and grounded recommendation. Checkout and cart recovery are **writes**. [ADR-0010](0010-read-only-mvp-tools.md) blocks writes until the approval queue exists; the queue needs a merchant console; the console is also what shadow-mode grading needs (**A4**, **E1**). One console unblocks both, and neither exists.

The tempting move is to build the console to unblock the writes. It is a milestone, not a step, and taking it would mean agent #2 arriving after a console nobody has yet needed in anger.

### The risk that shapes the architecture

[Blueprint §4.1](../../business/blueprint-v2.md) states it plainly and this ADR exists partly to record it as a decision rather than a paragraph: **the agent-commerce standards are young and may consolidate or change.** Some of what exists today will not exist in three years. A design that binds our data model to whichever protocol currently looks dominant inherits that protocol's mortality.

## Decision

### 1. Agent #2 is NEURA-SELL, restricted to the read-only third of its blueprint scope

**In:** grounded product recommendation, an MCP server over the catalogue, a machine-readable product feed.

**Out:** agent-facing checkout, cart recovery, personalised or behavioural ranking, dynamic pricing, reviews and ratings, AEO/GEO measurement, policy questions.

The full design is [`docs/agents/sell.md`](../../agents/sell.md). This ADR records *why*; that document records *what*.

### 2. SELL is one product with three surfaces, and only one of them is an agent

Only the recommendation surface has a graph. The MCP server and the feed have no nodes, no prompts and no LLM call of ours anywhere in them. The manifest and the entitlement gate all three, which is what makes them one sellable product — but they are not an agent in [the glossary](../../glossary.md)'s sense and calling them one would be a tidy fiction.

[`docs/agents/README.md`](../../agents/README.md) already draws this distinction for GUARD, whose MVP portion is platform infrastructure rather than an agent. This applies the same honesty to SELL.

**The consequence is that the safety argument changes shape across the surfaces**, and must not be carried over by habit. CARE's argument is *a persuaded model achieves nothing, because no tool that changes a store was ever registered*. On MCP and the feed there is no model of ours to persuade; the argument is read-only tools, the policy engine, tenant isolation, and nothing else.

### 3. Every protocol is an output format, and the canonical model is the only source

**We build against our own canonical model and render outward.** MCP is a rendering. Schema.org JSON-LD is a rendering. A merchant-feed RSS document would be a rendering. An agentic-commerce checkout format, when writes are unblocked, will be a rendering.

The commitment that gives this teeth:

> **Adding, changing or removing a protocol must never require a change to `neura-domain`, the adapter protocol, the sync engine, or an agent's graph.** If a format demands one, that is the signal to reconsider the format — not the model.

So a protocol dying costs us **one renderer**. This is the same shape as [ADR-0003](0003-canonical-domain-model.md)'s argument about platforms — no agent learns that Shopify exists — extended one layer outward: no agent learns which agent-commerce protocol is currently winning.

### 4. Two structural controls carry the product's central claim

*Grounded recommendation* is a claim, and these are what make it a property.

**A recommended product that was not retrieved is a fabrication, and it is detectable in code.** Every product id in a reply must appear in the deterministic `shortlist` node's output. This is *authorisation is code* ([AGENTS.md](../../../AGENTS.md) rule 3) applied to recommendation: not a judgement, not a threshold, not a model grading a model — a set membership test, gated at 1.00.

**"We do not sell that" is a claim about the whole store, and it is only safe when the evidence covers the whole store.** A cold index, a half-finished first sync or a timed-out adapter produces an empty candidate set indistinguishable from a store that genuinely does not stock the item — and collapsing the two tells a shopper that a fully stocked store is bare. So the honest-miss path is reachable only when the index is populated, the sync is fresh, **and** a live search also returned nothing. Otherwise the turn escalates. This is `verify`'s fail-closed rule one node earlier: a missing verdict reads as *not established*, never as *no objection raised*.

### 5. What was considered and rejected

| Option | Why not |
|:--|:--|
| **MIND as agent #2** | Needs an adapter-protocol change on every merchant's bridge, a wholesale order sync that was refused on purpose, or a superseding ADR on document storage. Three expensive doors; SELL needs none. **Recorded so it is not re-litigated.** |
| **SELL with checkout, behind a new approval queue** | Builds a console before a merchant has asked for one, and delays agent #2 behind it. [ADR-0010](0010-read-only-mvp-tools.md) is not blocking arbitrarily — it is waiting for evidence about which writes are actually requested. |
| **Recommendation only; MCP and feed later** | The cheapest two-thirds would be dropped. They re-expose the tool layer and the synced entities with no new capability, no new sync and no new domain model — [blueprint §4.1](../../business/blueprint-v2.md)'s *marginal cost, not new construction*, which is verifiably true for this scope. |
| **Bind the feed to one dominant protocol's schema** | Makes that protocol's lifetime our lifetime. It is the specific failure §4.1 names. |
| **Behavioural or personalised ranking in the MVP** | Needs history a new tenant does not have. It would import the entire cold-start ramp, and the ramp needs shadow grading, and grading needs the console. Excluding it is what makes SELL shippable **now**. |
| **Ship the feed authenticated** | Then answer engines cannot read it, and the feature has no consumer. The exposure question is real and is registered as **S7**, not resolved by quietly picking the safe-looking option that removes the point. |

## Consequences

**Good.** Agent #2 exists without a single change to `neura-domain`, the adapter protocol, the conformance suite or any merchant's bridge — the expandability claim in [agent-runtime §7](../agent-runtime.md) tested for the first time by something other than the agent it was written for. It is a **new channel** for the merchant rather than a cost saving, which [blueprint §4.1](../../business/blueprint-v2.md) argues is a materially easier sale than CARE's. Two agents make a conversation with a merchant possible where one did not. And the whole scope stays inside [ADR-0010](0010-read-only-mvp-tools.md), so nothing here can damage a store — a pilot stays as defensible as it is today.

**The cost, stated as plainly as ADR-0022's was.** Two of the three surfaces are outside the eval harness's reach, because neither has a model whose behaviour can regress. Rule 4 was written for surfaces that do. Their gate is a deterministic abuse and conformance suite, and **that substitution is a real weakening of a rule this project relies on** — registered as **E8** rather than quietly assumed to be equivalent.

**A new risk direction, and it arrives with this decision.** Merchant catalogue text is already classed as untrusted content. MCP and the feed serve it **outward, to other people's agents**, over a channel those agents have reason to trust. **We become the supply side of indirect injection.** Decided: run the existing deterministic guard rules over outbound text, write an audit event, surface it to the merchant, and **do not modify their copy** — silently editing a merchant's product description is editing their store. Not decided: whether we ever *withhold* a flagged product from an outbound surface (**S8**).

**Bad / accepted.** The catalogue tools are duplicated between CARE and SELL, because an agent may not import another agent (**A12**). A shopper cannot move between the two agents mid-conversation — cross-agent communication is the event bus in Phase 3 — so a merchant who buys both still has shoppers escalated at the boundary (**A13**). Policy questions escalate from SELL, at a real buying moment. And the feed is unauthenticated by necessity, which puts a per-tenant surface outside the authentication model entirely (**S7**); publication is close to irreversible once crawlers cache it.

**What cannot be claimed, and this is a consequence rather than a caveat.** SELL is not sellable on a conversion number. [Blueprint §5.2](../../business/blueprint-v2.md) already refuses a conversion-lift claim, we have no attribution, and a read-only agent cannot see whether anyone bought. What can be shown honestly is groundedness, honest-miss behaviour and availability accuracy — *"it never recommends something we do not have"* is checkable by a merchant in an afternoon, which an unverifiable percentage is not.

**Nothing here is validated.** The golden dataset will be synthetic, exactly as CARE's 47 are, and a synthetic suite proves the harness works rather than that the agent does (**E1**). There is still no design partner (**B2**). Every intent, threshold and cut in the design was chosen by people who have not watched a shopper use it.

## Revisit when

- **A design partner exists** and has told us which of the three surfaces they actually wanted. That is the evidence [`agents/README.md`](../../agents/README.md) wanted before this decision and could not have.
- **The approval queue and merchant console are built**, at which point checkout and cart recovery become available under [ADR-0010](0010-read-only-mvp-tools.md) tier 2, and this scope's exclusions should be re-read rather than assumed still binding.
- **A rendered protocol changes materially or dies.** The claim in §3 is that this costs one renderer. The first time it happens is the test of whether that is true, and the result belongs in a superseding ADR either way.
