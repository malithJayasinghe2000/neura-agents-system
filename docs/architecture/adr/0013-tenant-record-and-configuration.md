# ADR-0013 — The Tenant Record: One Table, Typed Where It Is Enforced

**Status:** Accepted · **Date:** 2026-08-02

## Context

[ADR-0008](0008-multi-tenancy-rls.md) decided how tenants are *isolated* and deferred what a tenant *is*: "tenant self-serve signup, a tenant admin portal, and billing" were explicitly out of scope, because they are product surface and the isolation model is not.

Milestone 1.13 has to close that gap, and until it does, `tenant_id` is a string that appears in every table and corresponds to nothing. There is no record to hang an entitlement on, no place to put a budget, and no answer to "which store does this tenant's agent talk to?". [tenancy-and-packaging.md §3](../tenancy-and-packaging.md) describes the entitlement layer as the thing that makes one codebase sell as five products, and shows it as a field on a tenant row that does not exist yet.

Three questions had to be answered together, because the answer to each constrains the others:

1. What is the tenant table's key, given that every other table's tenant column is called `tenant_id`?
2. Which per-tenant settings are columns, and which are a JSON blob?
3. Where do a merchant's store credentials live?

## Decision

**One `tenants` table, plus a `tenant_stores` table for connections. Typed columns for what the platform enforces; a JSONB `config` for behavioural knobs.**

### The primary key is `tenant_id`, not `id`

The conventional name would make `tenants` the one tenant-scoped table that `tests/integration/test_migrations.py` cannot see, because that test finds tables by looking for a column literally named `tenant_id`. A table it cannot see is a table whose missing policy nobody notices — which is precisely the hole ADR-0008 warns about for LangGraph's checkpoint tables, arriving by a different route.

It costs one small oddity in a schema and buys automatic coverage for the table whose leakage would expose every merchant's name at once.

### Typed columns for what is enforced, JSONB for what is configured

| Column | Why it is not in the blob |
|:--|:--|
| `status` | Authentication reads it and fails closed. A suspended tenant must be refused, and a status hidden in JSON is a status nobody indexes or constrains. |
| `enabled_agents` | The entitlement layer. It is queried, and it is the field an upgrade writes ([tenancy-and-packaging.md §3.2](../tenancy-and-packaging.md)). |
| `config` | Everything else: budget ceilings, the tool allowlist, tool-call limits. Schema-evolvable without a migration, validated on read by `TenantConfig`. |

Unknown keys in `config` are **ignored**, not rejected. A config written by a newer deployment must not stop a rolled-back one reading its own tenants.

### Every field in `TenantConfig` is read by something

Retention days, plan names, locales and trial flags are all obvious things to put in a tenant record, and none of them is here. This project has recorded the same failure twice — a `pii_leaked` assertion scored by nothing for two milestones, and `guard.block` events that nothing reads (open question S5). A knob that no code consults is a setting that appears to work, and the appearance is the damage.

**No `plan` column**, in particular. Plan names are pricing, and [blueprint-v2 §8](../../business/blueprint-v2.md) prices are proposals that are explicitly not to be published until pilot unit economics exist. Storing them would make an undecided thing look decided; entitlements are `enabled_agents`, which is what actually gates anything.

### Store credentials are enveloped, one data key per connection

`tenant_stores` holds AES-256-GCM ciphertext and a wrapped data key. The KEK comes from the environment and is never in the database, so a dump of this table is worthless — the argument in [security-model.md §5](../security-model.md), now implemented rather than described.

**One deviation from that section, made deliberately.** It says "DEK (per tenant, stored wrapped)"; this is per *connection*. A connection is the unit that is created, rotated and deleted, and a per-connection key means disconnecting a store destroys its key rather than leaving one key covering rows of mixed age. Rotation still rewraps a handful of keys rather than re-encrypting credentials, which is the property the envelope scheme was chosen for. Every wrap is bound to the tenant as additional authenticated data, so a wrapped key copied into another tenant's row fails to unwrap instead of quietly working.

The `platform` column stores a platform identifier **as data**. That is not a breach of rule 1: the rule forbids platform-specific *behaviour* in this layer, and a string reported by the merchant's own adapter is how the core stays ignorant of which platforms exist.

## Consequences

**Good**

- A tenant is now a thing. Entitlements, budgets and store credentials have somewhere to live, and `AgentNotEnabledError` — declared in milestone 1.2 and raised by nothing since — is finally raised by code.
- Onboarding a second tenant is a row, as ADR-0008 promised: `make tenant-new NAME="…" AGENTS=care`.
- The four new tables inherit the existing isolation test rather than needing their own, and one of them only because of the primary-key naming decision above.
- An upgrade is `UPDATE tenants SET enabled_agents = …`. No deploy, no migration, exactly as [tenancy-and-packaging.md §3.2](../tenancy-and-packaging.md) claims.

**Bad / accepted**

- **`tenants.tenant_id` will look wrong to every reader who has not read this ADR.** Mitigated by a comment in the schema pointing here.
- **JSONB config is not constrained by the database.** A malformed row is caught on read by Pydantic rather than on write by PostgreSQL. Accepted because the alternative is a migration per knob, and because the only writer is our own code.
- **There is no control plane.** The admin script runs as the ordinary application role, and creating a tenant works because the insert is scoped to the id being created. That is adequate for a pilot with one operator and is not an authorisation model; a real one belongs with the merchant console.
- **KEK custody is still an environment variable** — open question S2, unchanged. This ADR makes the encryption real; it does not make the key custody production-grade, and cloud KMS is still required before the first real merchant.

## Alternatives considered

- **`tenants.id`, with the isolation test taught about an exception.** Rejected: the test would then carry a list of tables it treats specially, and a list of exceptions is where the next hole goes.
- **A column per setting.** Rejected: a migration to change a budget is friction that leads to budgets being set in environment variables instead, which is per-deployment rather than per-tenant and therefore not a tenant setting at all.
- **Everything in JSONB, including `status` and `enabled_agents`.** Rejected: both are read on the authentication path and both gate access. What gates access should be constrained and queryable.
- **Credentials in a secrets manager rather than in Postgres.** Genuinely better, and the right answer once there is a cloud to depend on. Rejected for now because it makes local development and the sovereign tier depend on an external service, and the envelope scheme already gives the property that matters — a database dump alone is useless.
