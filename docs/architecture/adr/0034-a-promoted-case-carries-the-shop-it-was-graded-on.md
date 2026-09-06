# ADR-0034 — A Promoted Case Replays The Evidence Its Turn Captured

**Status:** **Accepted** — decided by owner review 2026-09-06, revising the 2026-09-06 proposal · **Date:** 2026-09-06 · **Builds on:** [ADR-0032](0032-a-graded-turn-becomes-an-eval-case.md), [ADR-0021](0021-synced-entities-are-documents.md) · **Clarifies** ADR-0032 §12's implementation; **does not amend it** · **Answers:** the blocker measured on 2026-09-06, and **not** [E1](../../open-questions.md), which stays open

## Context

[ADR-0032](0032-a-graded-turn-becomes-an-eval-case.md)'s promotion step was built on 2026-09-05 and all seven `agree` turns were promoted on 2026-09-06. Three failed:

```
CARE  2/4 passed   synthetic 0/4   is_validation True
SELL  2/3 passed   synthetic 0/3   is_validation True
```

**Two of the three failures are not the agent's.** `graded_care_002` answered *"We could not find any waterproof jackets in our catalogue"* and `graded_care_004` listed *Visa, Mastercard, American Express, Apple Pay, Google Pay* with no cash on delivery. **Both are correct answers about a different shop.**

The grade comes from the merchant's store; the eval runs against `fixtures/store.json`, written in July to exercise the harness. `graded_care_001` passes only because both happen to say *30 days*.

### The frozen fixture is correct and is not the fault

`evals/store.py` states the reason in its own docstring: a suite whose failures are ambiguous between *"the agent regressed"* and *"the shop changed"* is a suite nobody acts on. **That reasoning is upheld.** The fix is not to point evals at a live store; it is to give a promoted case the evidence its turn actually saw, frozen.

### Three candidate sources, measured 2026-09-06

| source | result |
|:--|:--|
| **The audit log** | **Empty of this.** `audit_log` holds 4 rows, every one `guard.block`. `AuditEvent` defines `TOOL_DECISION`, `TOOL_EXECUTED`, `LLM_CALL`, `RETRIEVAL` and `ESCALATION`, and **nothing in this repository writes any of them**; `executor.py` records `tool_executed` to the structured logger, which is not durable. |
| **The graph checkpoints** | **`agent_checkpoints` holds 0 rows.** |
| **`shadow_turns.citations` + `synced_entities`** | Resolves — and **is the wrong answer**, see below. |

**The merchant is told otherwise.** [`review.py`](../../../packages/neura-agent-core/src/neura_agent_core/review.py) renders *"This lookup ran. What it returned is customer data and is kept in the audit log, not in this queue."* **It is kept nowhere.** That sentence is [Finding 20](../../TESTING_LOG.md)'s shape — a screen describing a feature that does not exist — and §10 below corrects it. **A full tool-decision audit trail is deliberately not built here**: it is a security-model change with its own retention argument, and this ADR needs turn-time evidence, which is a different artefact with a different lifecycle.

### Why reconstruction from `synced_entities` was rejected

The 2026-09-06 proposal would have rebuilt each case's store by joining `shadow_turns.citations` to today's `synced_entities` rows. **It resolves, and it is still wrong**, for three reasons that were measured rather than argued:

1. **It reconstructs history from present state.** `synced_entities` holds what the last sync saw, not what the turn saw. For `graded_care_002` **all five** cited entities — three products, two categories — have `updated_at` later than the turn's `created_at`. The shop was re-synced on 2026-09-05; the grades are from 2026-09-03. A case built that way asserts a human's approval against data that human never saw.
2. **It cannot reproduce the boundary the turn crossed.** `search_products` on the merchant's store returned three products for the graded question. The fixture store's matcher requires **every** term to match, so against the same catalogue `waterproof jacket` returns **0** while `waterproof` returns 3 and `jacket` returns 1. Reconstruction therefore fixes the data and leaves the case failing.
3. **It invites the wrong repair.** The obvious follow-up — loosen the fixture matcher — is imitating a merchant's search engine inside our harness, which would change every existing invented case and measure a search engine no merchant has.

**A snapshot per shop was also rejected.** One mutable file per store, rewritten as shops change, is an artefact whose meaning silently moves under the cases that cite it.

## Decision

> **A promoted case replays the evidence captured when its turn ran. It never reconstructs that evidence afterwards.**

### 1. Evidence is captured at turn time, or the turn is not promotable

An **evidence bundle** is recorded while the shadow turn executes, at the boundary where the agent meets the store. There is no later reconstruction path and none is provided: a turn that ran before capture existed **cannot** be promoted, and that is stated as a refusal rather than approximated.

### 2. The bundle is platform-neutral, typed, and content-addressed

Typed Pydantic models at the boundary ([`evidence.py`](../../../packages/neura-agent-core/src/neura_agent_core/evidence.py)), carrying:

| field | why |
|:--|:--|
| `calls` — every **successful** adapter call, with canonical arguments and canonical results | the replay surface |
| `tools` — the successful tool invocations, by name | provenance, and the PII refusal in §8 |
| `retrieval` — the retrieved context and its sources | the other half of the boundary |
| `entities` — canonical documents seen, by section | the exported fixture, and inventory derivation |
| `source_fingerprints` — a content fingerprint per entity | §9 staleness, and ADR-0032 §12's *"recorded and not built"* check |
| `capabilities` | a store that could not search must not replay as one that could |
| `store_id` | §7 |
| `prompt_revision`, `captured_at`, `schema_version` | which prompt produced the graded reply, and when |
| `content_hash` | the artefact's identity |

**Failed calls are not recorded.** A replay that reproduced a transport error would freeze one afternoon's network into a permanent assertion.

### 3. It is persisted durably, tenant-scoped, on the shadow turn's lifecycle

A new `shadow_evidence` table, written **in the same transaction as the shadow turn** — so *"withheld from the shopper"*, *"recorded for a human"* and *"reproducible later"* cannot come apart — under the same `tenant_isolation` RLS policy as every other tenant table.

**It follows shadow evidence retention, not the audit log's.** The audit log is append-only and hash-chained because it is evidence *about* the system for an auditor. This is evidence *for* the system, it contains a merchant's catalogue, and it must be deletable when a shadow turn is. Putting it in the hash chain would make a lawful deletion look like tampering.

### 4. Rows are immutable; artefacts are content-addressed

Insert-only. There is no update path, and re-recording the same turn is refused. The exported fixture is named by its content hash — `fixtures/graded/<hash>.json` — so two cases citing the same evidence share one file and no file's meaning ever changes under a case that cites it.

### 5. Promoted cases **replay**; they do not overlay, and the matcher is untouched

`EvalCase` gains an explicit `fixture_mode`:

| mode | behaviour | used by |
|:--|:--|:--|
| `overlay` — **the default** | today's behaviour exactly: `store.json` plus the case's named files | every existing invented case |
| `replay` | the recorded boundary answers; **the base fixture is not loaded** | promoted cases |

**Explicit, never inferred.** No filename convention, no "if the case is in `graded.yaml`" rule. A case says what it is, and an invented case that says nothing keeps the behaviour it has always had.

**The fixture matcher is not changed.** `waterproof jacket` returns what the merchant's store returned, because that is what was recorded — not because our fake search got cleverer.

### 6. A replay mismatch fails loudly and never returns an empty catalogue

An adapter call the bundle does not contain raises `ReplayMismatch`, naming the method, the arguments and the calls that *were* recorded.

**This is the most important line in the ADR.** Returning `[]` for an unrecorded call is indistinguishable from a shop that stocks nothing — which is exactly the failure this ADR exists to remove, reintroduced one layer down. `no_match` would then be reached honestly, the agent would say *"we could not find any"*, and the case would fail for a reason nobody could see.

### 7. `store_id` scopes evidence internally; exports stay platform-neutral

The data model permits several stores per tenant, and `tenant_stores` has carried a per-store id since it was written. Evidence is keyed `(tenant_id, store_id, …)` so two stores with colliding `external_id`s cannot be confused.

**`store_id` never reaches an exported fixture**, along with `tenant_id`, `neura_id`, `platform`, `synced_at` and `raw`. **`external_id` and `locale` survive** — the first is the canonical identifier every agent reasons with, the second changes what a correct answer *is*.

**`raw` is refused twice over:** it is the merchant platform's own payload, and a fixture carrying it would put a platform's field names into an agent package, which is [rule 1](../../../AGENTS.md).

### 8. Promotion refuses more than it accepts

| refused | why |
|:--|:--|
| no evidence for the turn | §1 — there is nothing to replay, and reconstruction is not offered |
| evidence that records no successful call **and** no retrieval | an empty bundle replays as an empty shop, which is §6's failure with extra steps |
| a fingerprint that no longer matches the entity today | §9 |
| any credential-shaped value anywhere in the bundle | a fixture is a file in git |
| any tool declaring `pii_output` | **customer and order data must not enter this repository**, and a shopper's order is exactly what shadow mode is most likely to have looked up |

The PII refusal is a **hard structural limit and is stated as one**: order-status turns cannot be promoted at all under this design. That is a real loss — order status is CARE's commonest question — and it is preferred to a repository that accumulates a merchant's customers.

### 9. Staleness is detected before it is mistaken for a regression

Each captured entity's fingerprint is compared, at promotion time, against the current synced document. A moved entity **refuses promotion** and names itself.

This is [ADR-0032 §12](0032-a-graded-turn-becomes-an-eval-case.md)'s *"better answer… recorded and not built"* — but **built differently from how §12 imagined it, and the difference matters.** §12 proposed using `synced_entities.fingerprint` and recorded a precondition: *"whether they carry a stable fingerprint has not been verified."*

**That column is not used, and the precondition is sidestepped rather than met.** The fingerprint on both sides is computed here, by one function, over the canonical document with provenance and `raw` stripped — at capture over what the store returned, and at promotion over `synced_entities.document`. So the comparison is stable by construction, and does not depend on the sync engine's own hashing being stable, which **remains unverified and is now nothing this depends on**.

**One limitation, stated rather than discovered later:** an entity absent from `synced_entities` is reported and does **not** refuse. Absence means the sync has never seen it, so there is nothing to compare; treating "unknown" as "changed" would block promotion on a sync that had not run.

**§12 is clarified, not amended.** It governs a case whose source *changes after promotion*, and its answer — the case fails, a human reads it — is unchanged. This governs the moment *before* promotion.

### 10. The false merchant-facing sentence is corrected

`review.py` no longer claims the tool result is kept in the audit log. It says what is true: the lookup ran, what it returned is the merchant's own data, and it is not in this queue. **No audit trail is built to make the old sentence true** — that is unrelated scope with its own security argument.

### 11. The seven cases promoted on 2026-09-06 are removed, not repaired

They predate evidence capture. Their evidence is **not recoverable faithfully** — §Context measured every cited entity as already moved — and attaching today's shop state to a two-day-old grade would manufacture exactly the false provenance `synthetic: false` exists to prevent.

**They are deleted in git, with the reason in the commit message** — ADR-0032 §9's rule, applied to its own output. New cases come from **newly run, newly graded turns** once capture is live.

## Consequences

**Good.** A promoted case becomes reproducible: the same question, the same boundary, the same answer, on any machine, for as long as the artefact exists. `graded_sell_003`'s failure — *escalated=False, expected True* — becomes readable as the real behaviour change it is, rather than one of three failures that look alike. And the fingerprint check ADR-0032 wanted exists.

**Costs, accepted.**

- **The seven graded turns are lost as cases.** Their grades remain the merchant's evidence; they are simply not tests.
- **Order-status turns can never be promoted** (§8). CARE's commonest question is permanently outside the golden set unless a future ADR designs a way to hold customer data that git does not.
- **Every turn now pays for recording**, whether or not it turns out to be shadowed — mode is resolved after the turn. Bounded by the tool ceiling, discarded when unused, and never serialised into a response.
- **A promoted case cannot exercise a path its turn did not take.** Replay answers what was recorded; it cannot answer a question the shopper did not ask.

**Unchanged and load-bearing.** Platform independence — the bundle holds canonical entities only, and `raw` is stripped at capture. Dependency direction — `evidence.py` sits in `neura-agent-core` and imports downward only, so both agents use it and neither imports the other. RLS — one more tenant table under the same policy. **Injection resistance stays 1.00**, and `make eval-guard-off` still proves it structurally.

**[E1](../../open-questions.md) stays open, and this ADR must not be read as closing it.** What was blocking E1 *mechanically* is fixed. What E1 actually asks — whether there is real graded volume from a real merchant — is untouched: every turn this design can promote is still one the project owner typed into his own test shop. **That is reproducibility, not validation**, and [CLAUDE.md §4](../../../CLAUDE.md) governs the difference. E1 closes with [B2](../../open-questions.md), not with this.

## Alternatives considered

**Reconstruct from `synced_entities` at promotion time.** Rejected — §Context. It rebuilds history from present state, and every entity had already moved.

**Run promoted cases against the live store.** Rejected — the exact ambiguity `evals/store.py` exists to remove.

**Loosen the fixture matcher so the recorded catalogue searches like the merchant's.** Rejected — it changes every existing invented case, and imitates a search engine no merchant has.

**Build the tool-decision audit trail and snapshot from it.** Rejected as the source. It records what a tool returned rather than the canonical boundary, it is append-only where this must be deletable, and it would not have helped: the rows do not exist for any turn already graded.

**One snapshot per shop, updated as the shop changes.** Rejected — §Context. A mutable artefact under an immutable assertion.
