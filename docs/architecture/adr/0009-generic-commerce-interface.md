# ADR-0009 — Generic Commerce Interface as the Primary Integration Tier

**Status:** Accepted · **Date:** 2026-07-25

## Context

[ADR-0003](0003-canonical-domain-model.md) establishes that adapters translate platforms into a canonical model. The open question is *which adapter to build first*.

`implementation_plan_1` assumed native adapters for Shopify, WooCommerce and Magento. But the stated requirement is integration with existing platforms **and with newly built or custom ones**, and the [ICP](../../business/blueprint-v2.md#3-ideal-customer-profile) is specifically merchants the Shopify-first incumbents ignore. A custom in-house store has no adapter anyone will ever write for it.

## Decision

The **Generic Commerce Interface** — a published specification of ~9 read-only REST endpoints plus a signed webhook contract, which any store implements — is the **primary integration tier and the MVP deliverable**.

It ships with an OpenAPI 3.1 spec generated from the canonical models, and a **`neura-conformance` CLI** that a developer runs against their own endpoint to see exactly what passes and what does not.

Native adapters (Tier 1) and feed/push mode (Tier 3) come later.

## Consequences

**Good**
- **A custom store can integrate without us writing anything.** That is the only way to serve the ICP at all.
- The spec *is* the canonical model serialized, so `GenericAdapter` validates and passes through — no second translation layer, and spec and code cannot drift.
- The conformance CLI makes adoption self-service. A developer fixes what the tool reports; there is no support ticket and no call with us. That difference is what separates a spec from an adoptable spec.
- Building it first **validates the abstraction early**. If the canonical model is wrong, making a real platform conform to it exposes that immediately — while it is still cheap to change.
- It positions the spec as a potential open standard ([blueprint-v2 §11.5](../../business/blueprint-v2.md)).

**Bad / accepted**
- It asks the merchant's developer for work, where a native adapter asks for nothing. This is why Tier 1 still exists for platforms with large installed bases; the tiers serve different customers.
- A published spec is a contract. Versioning and deprecation policy are needed before the first external adopter, not after.
- Read-only in v1 means write actions wait for a spec revision. Acceptable — [ADR-0010](0010-read-only-mvp-tools.md) makes the MVP read-only anyway.

## Alternatives considered

- **Shopify adapter first** — largest market, best API, and it would optimise for the segment we have explicitly decided *not* to compete in, while leaving the abstraction unvalidated.
- **A Bagisto-specific adapter** — fastest path to a working demo on the test store, and it would bake Bagisto-shaped assumptions into a "platform-agnostic" core. Rejected for that reason: Bagisto instead conforms *to* the spec, which proves the abstraction rather than bypassing it.
- **GraphQL or gRPC for the spec** — higher implementation burden for a merchant's developer. Plain REST + JSON is implementable by anyone in an afternoon, which is the actual design goal.
