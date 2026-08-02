# ADR-0014 — API Keys: SHA-256, and Reading One Row Before the Tenant Is Known

**Status:** Accepted · **Date:** 2026-08-02

## Context

[api-design.md §2](../api-design.md) and [security-model.md §5](../security-model.md) specify the credential: `fn_sk_…` server-side, `fn_pk_…` for the widget, "stored as hashes — we can verify a key, we can never display one after issue", scoped, expirable, revocable, with `last_used_at`.

Implementing that ran into a problem neither document anticipated, and it is the reason this ADR exists rather than the code simply following the spec.

**Authentication has to read a row before it knows which tenant it is acting for.** The tenant comes *from* the key. But [ADR-0008](0008-multi-tenancy-rls.md) says every business table is protected by Row-Level Security keyed on `app.tenant_id`, and `Database.tenant_session` is the only way to obtain a session — a transaction that has not set the variable matches no row anywhere. So the query that finds the API key cannot run.

There is an obvious way out, and it is the wrong one.

## Decision

### 1. The key is 256 random bits, stored as a SHA-256 hash

`secrets.token_urlsafe(32)`, formatted `fn_{sk|pk}_{live|test}_{43 chars}`. Stored as a plain SHA-256 of the whole token, with a global unique constraint so one token cannot authenticate as two tenants.

**Not bcrypt or Argon2.** Those exist to make *low-entropy human passwords* expensive to guess. There is nothing to guess here: a 256-bit random token is not in any dictionary and is not derived from anything. A deliberately slow hash on the authentication path would be a self-inflicted denial of service that every legitimate request pays for, to defend against an attack that the entropy already prevents.

**Not HMAC with a server-side pepper**, which is the other common answer. A pepper protects against a database dump when the hashed values are guessable — again, not the case here — and it introduces a real failure mode: rotating `NEURA_SECRET_KEY` would invalidate every key every merchant holds, silently, at deploy time. The cost is certain and the benefit is hypothetical.

**A displayable prefix is stored in clear** — `fn_sk_live_x7Kq2mBv` — because a merchant with four keys has to be able to tell which one to revoke, and the alternative is showing the whole key again, which is what hashing exists to prevent. It reveals 48 bits and leaves 208.

### 2. The bootstrap is a capability, not an exemption

The shortcut is to leave `api_keys` outside Row-Level Security as a "control plane" table. That creates the one table where a forgotten `WHERE tenant_id = …` leaks every merchant's credentials at once — and disables the test that would have caught it, since the test finds tables by their `tenant_id` column and an unprotected table simply reports as unprotected only if someone is looking.

Instead, **the hash of the key is itself the capability to read that key's row**:

```sql
CREATE POLICY credential_lookup ON api_keys
    FOR SELECT
    USING (token_hash = current_setting('app.api_key_hash', true));
```

`Database.credential_session(token_hash)` sets that variable, does **not** set `app.tenant_id`, and issues `SET TRANSACTION READ ONLY`. The result is a transaction that can read exactly one row of one table — the record of a credential the caller already holds — and nothing else in the database: no other key, no tenant, no conversation, no usage. Presenting a key you possess in order to learn about that key discloses nothing you did not already have.

Once the tenant is known, everything reverts to normal: a `tenant_session` loads the tenant, checks its status, and records `last_used_at`.

**Why this is not a hole.** The policy is `FOR SELECT`, so insert, update and delete still consult only the tenant policy — the bootstrap path cannot write, and `READ ONLY` makes that structural rather than careful. It cannot be used to enumerate, because guessing a hash is guessing the 256-bit token behind it. And anyone able to set a PostgreSQL session variable already holds the application's database role, in which case they could set `app.tenant_id` to any value they like; the widened policy grants such an attacker nothing they did not have.

### 3. Public keys are inert until origin-locked

`fn_pk_` keys are served to browsers and are therefore public knowledge. A public key is refused at issue time if no origin allowlist is given, and an empty allowlist permits **nothing** rather than everything. That is the direction an access control has to fail in: a widget key issued without origins is inert until someone configures it, rather than open to every site on the internet until someone notices.

### 4. Revocation is a timestamp

A deleted key leaves no answer to "what did this key do, and when did we stop it?", which is the first question asked after an incident.

## Consequences

**Good**

- **`api_keys` is under the same forced Row-Level Security as every other table**, so the "every tenant table is protected" test covers the credential store rather than being taught to skip it.
- Authentication costs one indexed lookup and one SHA-256. No stretching, no cache, no second store.
- A malformed token — a pasted password, a bearer JWT, an empty header — costs a regular expression and never reaches the database.
- Two integration tests state the property directly: the credential session sees exactly one row, and sees nothing at all in `tenants`, `tenant_usage` or `tenant_stores`.
- `last_used_at` is written at most once every five minutes per key, so stale-key detection does not cost an `UPDATE` on a hot row per request.

**Bad / accepted**

- **There is one policy in the system that is not "tenant_id equals the session variable".** It is the kind of exception that a future reader might copy without understanding. Mitigated by the migration comment, the docstring on `credential_session`, and this ADR — and by the policy being the narrowest possible shape: one table, `FOR SELECT`, keyed on a value that is itself a secret.
- **A database dump plus the ability to run arbitrary SQL as `neura_app` is still a full compromise.** True before this decision and unchanged by it; RLS is not a defence against the application's own role.
- **The hash is unsalted**, so identical tokens hash identically. Irrelevant for random tokens — there is no rainbow table for 256 bits of entropy — but worth stating rather than leaving a reviewer to wonder whether it was considered.
- **Revoked keys accumulate.** Deliberate; they are the audit trail. A retention pass belongs with the two-year audit-log policy, not here.

## Alternatives considered

- **`api_keys` outside RLS.** Rejected above: it is the single table where application-level filtering is least forgivable.
- **A second database role with SELECT on `api_keys` only.** Would work, and is the more conventional answer. Rejected because it adds a second connection pool and a second credential to every deployment — including the sovereign tier, where every moving part is the customer's to operate — to achieve what one policy achieves.
- **Look up by the clear prefix instead of the hash, then compare.** Rejected: the prefix is not unique by construction, so the policy would return several rows and the "one row, the one you hold" property — the entire defence — would be gone.
- **JWTs instead of opaque keys.** Rejected: a self-describing token cannot be revoked without a revocation list, which is the database lookup a JWT was supposed to avoid. Merchant-facing API keys are long-lived, and long-lived credentials must be revocable immediately.
