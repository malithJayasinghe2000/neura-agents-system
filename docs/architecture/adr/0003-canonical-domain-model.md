# ADR-0003 — Canonical Domain Model + Adapter Protocol

**Status:** Accepted · **Date:** 2026-07-25

## Context

The product's entire market position rests on working with *any* commerce platform — Shopify, WooCommerce, Magento, Bagisto, Odoo, or something built last month ([blueprint-v2 §3.1](../../business/blueprint-v2.md)). Every incumbent is Shopify-first, which is exactly why the segment is open.

The obvious shortcut — write against the first platform, generalise later — would make the core permanently platform-shaped. Generalising after the fact almost never happens.

## Decision

A **platform-neutral canonical domain model** in `packages/neura-domain` (pure Pydantic, zero I/O), and a **`CommerceAdapter` Protocol** in `packages/neura-commerce`. Adapters translate; nothing else knows a platform exists.

Adapters declare a **`capabilities` set**, and the agent's available tools are computed from it.

**Enforced by CI:** no commerce-platform name may appear outside `packages/neura-adapters/` and `docs/`.

## Consequences

**Good**
- Agents, tools, RAG and API are written once against one vocabulary.
- Adding a platform is one new file plus a registry entry — no core change.
- **Capability negotiation is also a security control**: a tool that is never registered cannot be invoked, however persuasive an injected prompt is ([security-model.md §2.1](../security-model.md)).
- The canonical model doubles as the published integration spec ([ADR-0009](0009-generic-commerce-interface.md)), so spec and code cannot drift.

**Bad / accepted**
- Real upfront cost before any feature is visible.
- Every canonical model is lossy. Mitigated by a `raw` field preserving the source payload, so an unmapped field is a lookup rather than a re-sync.
- Some platform-specific power is unreachable through a neutral interface. Accepted deliberately: reach across platforms is worth more to us than depth on one.
- The abstraction may prove wrong in places. It is validated early by making Bagisto conform to it rather than by writing a Bagisto-shaped adapter.

## Alternatives considered

- **Direct per-platform integration** — fastest to a first demo, and it forecloses the market position permanently.
- **A third-party unification API** (Rutter, Nango, Alloy) — real time saved, but it adds cost per tenant, becomes a hard dependency on someone else's roadmap, and it *is* the thing we are selling. Reconsider only for long-tail Tier-1 platforms.
