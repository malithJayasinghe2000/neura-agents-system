# ADR-0022 — A Durable Job Queue, And The One Read That Crosses Tenants

**Status:** Accepted · **Date:** 2026-08-26 · **Builds on:** [ADR-0002](0002-modular-monolith.md), [ADR-0008](0008-multi-tenancy-rls.md), [ADR-0014](0014-api-keys-and-the-rls-bootstrap.md), [ADR-0021](0021-synced-entities-are-documents.md)

## Context

Under [ADR-0008](0008-multi-tenancy-rls.md) no transaction can enumerate tenants. A session that has not set `app.tenant_id` matches no row in any policy-protected table, so the question every background worker needs to ask — *whose work is due?* — has no transaction that can ask it. That is the property the design exists to have, not a bug in it.

The project has now met this wall three times, and the record matters because it is what rules out the obvious answers.

**1.14, the webhook outbox.** Solved with a Redis set of tenant ids that the drainer reads, opening one scoped session per tenant named in it. The cost was stated rather than hidden: lose the set and the rows are safe but the schedule is not.

**1.16, per-tenant CORS origins.** A preflight carries no credential, so the allowlist would have to come from a union across every tenant. The 1.14 answer was **deliberately rejected** there — losing the webhook index costs a delayed schedule, losing a CORS index would cost a total widget outage — and [ADR-0019 §3](0019-widget-no-build-step.md) went around the question instead: the preflight grants permission to *ask*, and the key decides what may be *read*.

**Sync persistence, 2026-08-16.** [ADR-0021](0021-synced-entities-are-documents.md) made the synced catalogue durable, and left the last sentence of its own "what this does not decide" section as: nothing schedules a sync, because a worker cannot ask whose catalogue is due.

Two sightings had already established that **"do what the webhooks did" is not the general answer** — the cost of losing an out-of-band index is different on every surface. The third sighting is what forces a general one, because there is no way around it: a sync is background work by definition, and there is no incoming request whose credential could name the tenant.

**The observation that reframes the problem.** A durable job table with a `tenant_id` column — the shape this project's notes had assumed — does not on its own answer any of this. It is under the same RLS as the other sixteen tables, so it makes the *data* safe and leaves the *dispatch* exactly as impossible. Every answer has two halves, and only the second is actually open.

So the real question is not *job table or Redis*. It is: **the system needs exactly one place where a read crosses tenants — how narrow can that place be, and how loudly does it announce itself when it breaks?**

## Decision

### 1. `job_queue` — an ordinary tenant table

`job_queue` carries `tenant_id`, `kind`, `payload jsonb`, `status`, `run_after`, `attempts`, `max_attempts`, `locked_until`, `last_error`, `dedupe_key`, and the two timestamps. It takes the plain `tenant_id = current_setting('app.tenant_id')` policy with `ENABLE` and `FORCE`, exactly like every other tenant table, and it is covered automatically by the ADR-0008 protection test because it carries a `tenant_id`.

Every read, claim, update and delete of a job happens inside `Database.tenant_session`. Nothing about the job's *contents* is exempt from anything.

`kind` is a string and `payload` is `jsonb`, for the reason [ADR-0021](0021-synced-entities-are-documents.md) chose a document: a typed column per job kind would make PostgreSQL a second definition of what a job is, and `neura-domain` — which imports only Pydantic and the stdlib — must gain zero lines for a scheduling mechanism. The handler validates its own payload, the way the entity store validates its own document.

### 2. One `SECURITY DEFINER` function, owned by a role nothing connects as

```sql
CREATE ROLE neura_scheduler NOLOGIN;
GRANT SELECT (tenant_id, status, run_after, locked_until) ON job_queue TO neura_scheduler;
CREATE POLICY scheduler_dispatch ON job_queue FOR SELECT TO neura_scheduler USING (true);

CREATE FUNCTION neura_due_tenants(as_of timestamptz) RETURNS SETOF text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$ SELECT DISTINCT tenant_id FROM job_queue
      WHERE status = 'pending' AND run_after <= as_of
        AND (locked_until IS NULL OR locked_until <= as_of) $$;

ALTER FUNCTION neura_due_tenants(timestamptz) OWNER TO neura_scheduler;
REVOKE ALL ON FUNCTION neura_due_tenants(timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION neura_due_tenants(timestamptz) TO neura_app;
```

Four properties, each doing work:

- **`neura_scheduler` has no `LOGIN` and no `BYPASSRLS`.** Nothing connects as it. It is reachable only by being the definer of one function.
- **It has no grant on `payload`.** Column-level `GRANT` and row-level policy both have to pass, so even the elevated role cannot read what a job is *about* — only that one exists, for whom, and when.
- **The function returns `SETOF text`.** One column. It cannot be coaxed into returning a row, a payload, or anything from another table; the body is four lines of static SQL with no dynamic statement and a pinned `search_path`.
- **`neura_app` gets `EXECUTE` and nothing else.** The exemption is not reachable by writing a query — only by calling the one function, whose entire output is a list of tenant ids.

### 3. `Database.dispatch_session()` — read-only, and tenant-less on purpose

The worker calls the function through a third session type, alongside `tenant_session` and `credential_session`. It issues `SET TRANSACTION READ ONLY` and sets **no** `app.tenant_id`, so every table query from it returns nothing. The only useful statement it can make is the function call.

This is the same shape as the authentication bootstrap ([ADR-0014](0014-api-keys-and-the-rls-bootstrap.md)) and for the same reason: where a genuine chicken-and-egg exists, the answer is a session that can ask exactly one narrow question, not a session that has been let off.

### 4. The alternatives, and what each would have cost

| | what can cross tenants |
|:--|:--|
| a `BYPASSRLS` role | every row of every table, on every query the worker ever makes, for as long as it runs. A missing `WHERE tenant_id` becomes a cross-tenant leak instead of an empty result — and the mechanism [`Database.assert_isolation_applies`](../../../packages/neura-core/src/neura_core/db.py) exists to refuse would be running by design |
| a GUC-gated policy exemption on `job_queue` | every column of every job row, payload included, reachable from any application session that sets the GUC |
| **this** | one column-set of one table, for the duration of one call, through a role nothing connects as |

`BYPASSRLS` is the shape to argue against and this is the argument: it is not narrower or wider than the others by degree, it removes the property rather than bounding it.

### 5. A lease, and therefore at-least-once

A claim sets `status='running'` and `locked_until = now() + lease`. A worker that dies mid-job leaves a row whose lease expires and which becomes due again. This is **at-least-once, not exactly-once**: a stalled worker and its replacement can both run the same job.

That is free for sync, because [ADR-0021](0021-synced-entities-are-documents.md)'s `ON CONFLICT` on the natural key already makes a repeated crawl converge on the same rows. It is not free in general, and any job kind with an external side effect has to argue its own idempotency before it is added — stated here so that it is an argument someone has to make, rather than an assumption they inherit.

### 6. A job that cannot be run is dead-lettered, never dropped

An unparseable payload, an unknown `kind`, or a handler that raises increments `attempts`, records `last_error`, and re-schedules with backoff until `max_attempts`, after which the row is `dead` — logged at ERROR and still readable in the tenant's own scoped session. It is not skipped, for the reason `StoredEntityInvalidError` is not skipped: work that disappears quietly is a defect found by a merchant.

## Consequences

**Good.** Background work becomes possible at all: a worker that is told nothing can discover that a tenant it has never heard of has a catalogue due. The schedule is written in the same transaction as the thing that scheduled it, which Redis structurally could not do — a `sadd` after a commit strands the work if the process dies in between. The schedule is in the backup, because it is in the database the backup is of. And the queue carries the work rather than a hint that work exists: what, when, how many attempts, and why it last failed.

**The cost, stated as plainly as 1.14's was.** There is no separate index to lose, so *"lose the index and the schedule is lost"* is no longer a failure this system has. What replaces it is a real exemption: **a role exists that can see, for every tenant, that a job is pending and when.** Tenant ids and timing — no merchant content, no payload, no conversation, no key. That is the entire blast radius and it is one query to check.

**The failures that remain, and why none is silent.** A missing migration means the function does not exist and the first poll raises, every cycle, in the log — it cannot present as "nothing to do", which is precisely how an empty Redis `SMEMBERS` presented. A bad payload dead-letters visibly. A dead worker's job comes back. The one thing that can still lose the schedule is losing PostgreSQL, which is a total outage and not a quiet one.

**Bad.** One more role to provision, and a migration that needs `CREATE ROLE` — so a deployment whose migration role lacks it fails loudly at migrate time rather than starting with a broken scheduler. Cross-tenant fairness is coarse: the dispatcher sweeps tenants in whatever order the function returns them, and one tenant with ten thousand due jobs is bounded only by the per-tenant claim limit.

## What this does not decide

- **The webhook drainer stays on its Redis index for now.** Its outbox rows are already durable and correct; what is wrong is only the *index*, and the migration is to enqueue a `webhook.drain` job in the same transaction as the delivery rows and delete `PENDING_TENANTS_KEY`. Kept out of this change deliberately: the fair test of a dispatch mechanism is a surface that has none today, and if delivery breaks in a commit that changed both, nothing says which half did it.
- **No recurring schedule.** Jobs are enqueued by something; nothing yet enqueues one on a timer. A `cron`-shaped table is a later decision, not a column added quietly here.
- **No retention, budget-reset or approval-queue jobs.** P7 named all three as the work this unblocks. This decides how they will be dispatched, and none of them is designed.
- **Fairness and priority.** No priority column, no per-tenant quota beyond the claim limit. Adding either is a decision with evidence behind it, and there is no evidence yet.
