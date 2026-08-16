# ADR-0021 — A Synced Entity Is Stored As Its Canonical Document, Not As A Second Schema

**Status:** Accepted · **Date:** 2026-08-16 · **Builds on:** [ADR-0003](0003-canonical-domain-model.md), [ADR-0005](0005-pgvector-not-qdrant.md), [ADR-0008](0008-multi-tenancy-rls.md)

## Context

`EntityStore` and `SyncStateStore` have been Protocols with in-memory implementations only since milestone 1.8. The engine above them is complete — resumable backfill, incremental polling, webhook refresh, reconciliation, per-tenant throttling — and every one of those mechanisms loses its entire result when the process ends. A backfill of a real catalogue is a long crawl whose only product is a data structure that does not survive a redeploy.

Persistence was considered for 1.13 and deliberately excluded, for reasons recorded in that session's entry: it is not a tenancy problem, nothing in 1.13 or 1.14 depended on it, and RAG — the one thing that genuinely needs durable data — already has `document_chunks`. What 1.13 bought it was the RLS convention and the migration pattern, applied four more times since.

Filling the seam forces one decision that the Protocols deliberately left open, because it is the decision that determines **where the canonical model is defined**.

## Decision

### 1. One table, one `jsonb` document

`synced_entities` holds the result of `model_dump(mode="json")` in a `document jsonb` column. Its primary key is `(tenant_id, platform, entity_type, external_id)` — exactly `EntityKey` — alongside `neura_id`, `fingerprint`, `created_at` and `updated_at`. There is no column for a title, a price or a status, and there is not one table per entity type.

`neura-domain` remains the only place a `Product` is defined. PostgreSQL stores it and does not interpret it.

**The alternative was five typed tables**, and it fails on what it would cost rather than on what it would buy. It makes the database a second definition of the canonical model, so every field added to `Product` becomes a migration in a package that is supposed to import only Pydantic and the stdlib. Three of the five tables would be empty: [commerce-integration.md §6.1](../commerce-integration.md) syncs catalogue, categories and policy text, and reads orders and customers live through the adapter, because an order status an hour stale is a worse failure than a 400ms answer.

**And nothing needs it.** Every read in the `EntityStore` protocol — `get`, `external_ids`, `count`, `fingerprints` — filters on the key or a prefix of it. No caller filters a synced entity by its contents. Semantic search over that text is `document_chunks` and pgvector ([ADR-0005](0005-pgvector-not-qdrant.md)), which is a different table for a different question.

**The accepted cost, stated plainly:** PostgreSQL cannot enforce that a row is a valid `Product`. Nothing stops a hand-written `UPDATE` from producing a document the domain model rejects.

### 2. A stored document is validated on read, and a failure is an error

Because the column cannot type-check, Pydantic does — on the way in, where the value is already a `CanonicalEntity`, and on the way out, where `model_validate` runs against the canonical model.

A row that fails raises `StoredEntityInvalidError`. It is **not** skipped. A store that quietly dropped rows it could not parse would report a shrinking catalogue, and "the agent stopped knowing about twelve products" is a defect found by a shopper rather than by a test. This is the same reasoning as the RAG indexer naming the records it skips instead of silently omitting them.

### 3. Both primary keys are natural and composite

`synced_entities`' key is `EntityKey`; `sync_checkpoints`' is `SyncKey`. Neither table has a surrogate id.

A surrogate would permit two rows for one entity, and the store contract's first commitment is that duplicates are structurally impossible — webhooks are delivered twice, backfills overlap incrementals, and a reconcile rewrites what is already there. With the natural key, `ON CONFLICT` is the whole of the idempotency argument.

Neither table carries a secondary index, because every read filters on a prefix of its primary key. An index beyond that would be one nothing uses.

### 4. The recorded `neura_id` survives a content change

An adapter mints a fresh `neura_id` on every fetch. The store keeps the one it recorded first and stamps it onto the document it writes back.

This corrects a defect the in-memory implementation had and could not be blamed for: in memory, an id that changes when a merchant edits a product title outlives nothing, so nothing could observe it. Durably, it contradicts the stated purpose of [identity.py](../../../packages/neura-commerce/src/neura_commerce/identity.py) — *"our ids never change even if a merchant migrates platforms"* — and would break a conversation that referred to an order last week. Both implementations now behave the same way.

### 5. Forced RLS, and the plain policy

Both tables take `tenant_id = current_setting('app.tenant_id')` with `ENABLE` and `FORCE`, and both are reachable only through `Database.tenant_session`. Nothing here runs before the tenant is known, so neither needs the widening that `api_keys` required for the authentication bootstrap ([ADR-0014](0014-api-keys-and-the-rls-bootstrap.md)).

## Consequences

**Good.** The canonical model is untouched — this milestone adds zero lines to `neura-domain`, and a field added to `Product` tomorrow needs no migration. The synced catalogue survives a restart, which is what the whole sync engine was for. The two new tables are covered automatically by the ADR-0008 protection test, because they carry a `tenant_id`.

**Bad.** No SQL predicate over an entity's contents, and no database-level validation. A merchant-facing report that wanted "products under £20" would have to read documents or add a projection.

**The line this ADR draws.** The day something genuinely needs to *query* synced entities relationally, that is a superseding ADR — not a column added quietly to `synced_entities`, and not a `jsonb` GIN index bolted on to make one query fast. Either would start the second definition of the domain model that this decision exists to prevent.

## What this does not decide

- **The identity map is still in memory.** `synced_entities.neura_id` is the durable half for synced types; `EntityMap.reverse` is not persisted, and nothing reads it yet.
- **No retention or offboarding fan-out.** [security-model.md §6.2](../security-model.md) requires deletion to reach every table holding a tenant's data. These two are now on that list and the fan-out itself remains unbuilt.
- **Nothing schedules a sync.** The worker still has no scheduler, and under RLS it cannot enumerate tenants to build one — that is open question **P7**, unchanged by this.
