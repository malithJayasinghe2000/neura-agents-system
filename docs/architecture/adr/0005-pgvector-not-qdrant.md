# ADR-0005 — pgvector in PostgreSQL, Not a Separate Vector Database

**Status:** Accepted · **Date:** 2026-07-25

## Context

RAG needs vector search over catalogue, policies and FAQs. `implementation_plan_1` specified Qdrant, self-hosted via Docker, alongside PostgreSQL and Redis.

Expected scale per tenant: thousands to low hundreds of thousands of chunks. Sovereign deployments run on a customer's own hardware, where every additional service is a support burden ([blueprint-v2 §4.3](../../business/blueprint-v2.md)).

## Decision

**pgvector inside the primary PostgreSQL instance**, behind a `VectorStore` interface in `packages/neura-agent-core`.

## Consequences

**Good**
- One fewer service to run, back up, monitor, secure and — for sovereign customers — install.
- **Transactional consistency**: a product and its embeddings commit together. With a separate store, a partial failure leaves vectors pointing at products that no longer exist, and that drift is invisible until retrieval goes wrong.
- Metadata filtering (`tenant_id`, `embedding_model`, `source_type`) is a plain `WHERE` clause, using the same Row-Level Security that protects everything else ([ADR-0008](0008-multi-tenancy-rls.md)). With an external store, tenant isolation must be reimplemented and separately verified.
- One backup restores the whole system to a consistent point.

**Bad / accepted**
- pgvector is slower than a purpose-built engine at millions of vectors. Far beyond current scale, and the interface makes swapping mechanical.
- Vector search competes for the same database resources as transactional queries. Monitored; a read replica is the first mitigation.
- Index tuning (HNSW parameters) is more manual.

## Alternatives considered

- **Qdrant** (the original plan) — faster at scale, good Python SDK, but a whole extra service, no transactional consistency with the source data, and a second tenant-isolation implementation to get right.
- **Pinecone / hosted** — operationally simplest, but a per-tenant cost, and structurally incompatible with the sovereign tier since data would leave the customer's boundary.

## Revisit when

Any single tenant exceeds roughly 1M chunks, or vector query latency intrudes on the p95 conversation budget.
