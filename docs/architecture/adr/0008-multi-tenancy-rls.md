# ADR-0008 — Multi-Tenancy via PostgreSQL Row-Level Security, From Day One

**Status:** Accepted · **Date:** 2026-07-25

## Context

The platform serves many merchants from one deployment. Each tenant's catalogue, orders, customer conversations and configuration must be completely isolated.

Phase 1 has exactly one tenant — a test store — which makes it tempting to defer tenancy. That temptation is the trap: retrofitting isolation means touching every query, every cache key, every vector namespace and every migration, and cross-tenant leakage is the failure a B2B platform does not recover from.

## Decision

**Multi-tenancy from the first migration.** A shared schema with `tenant_id NOT NULL` on every business table, protected by **PostgreSQL Row-Level Security**. The application connects as a non-superuser role to which RLS applies, and sets `SET LOCAL app.tenant_id` per transaction from the authenticated request context.

Isolation is layered: RLS · vector namespaces `(tenant_id, embedding_model)` · Redis key prefixes `t:{tenant_id}:` · per-tenant adapter credentials · CI tests that attempt cross-tenant reads and must fail.

**Deferred:** tenant self-serve signup, a tenant admin portal, and billing. Those are product surface; the isolation *model* is not.

## Consequences

**Good**
- **A forgotten `WHERE tenant_id = ...` returns nothing instead of leaking.** This is the entire argument. Application-level filtering alone assumes no developer ever forgets, across every query, forever.
- Isolation is enforced at the layer closest to the data, so it also covers ad-hoc queries, admin tooling and background jobs.
- Onboarding a second tenant is a row, not a project.
- One database, one migration set, one backup — far cheaper than schema- or database-per-tenant at this scale.

**Bad / accepted**
- RLS has a small query-planning cost, and policies must be written and tested per table. Ongoing discipline: a new table without a policy is a hole, so the migration review checklist includes it.
- Debugging is less obvious — a query returning nothing may be an RLS session-variable problem rather than missing data. Documented in `AGENTS.md`.
- Connection pooling must not leak session state between tenants. `SET LOCAL` (transaction-scoped, auto-reset) is used rather than `SET`, specifically for this reason.

## Alternatives considered

- **Schema-per-tenant** — stronger isolation, but migrations multiply by tenant count and connection management gets awkward. Revisit only for an enterprise customer demanding physical separation.
- **Database-per-tenant** — strongest isolation, highest operational cost. This is effectively what the sovereign tier is, and there it is a *product*, not the default.
- **Application-level filtering only** — what most projects do, and it depends on perfect discipline in every query forever. One miss is a breach.
