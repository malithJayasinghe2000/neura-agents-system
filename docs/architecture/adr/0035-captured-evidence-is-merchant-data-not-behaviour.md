# ADR-0035 — Captured Evidence Is Merchant Data, Not Behaviour

**Status:** **Accepted** — owner decision, 2026-09-06 · **Date:** 2026-09-06 · **Builds on:** [ADR-0034](0034-a-promoted-case-carries-the-shop-it-was-graded-on.md), [ADR-0003](0003-canonical-domain-model.md) · **Narrows** the scope of the platform-independence *check*; **does not change** [rule 1](../../../AGENTS.md) · **Resolves:** [C6](../../open-questions.md)

## Context

[ADR-0034](0034-a-promoted-case-carries-the-shop-it-was-graded-on.md) shipped on 2026-09-06 and the first real promotion failed immediately — not on its own logic, but on the repository's most important check.

`scripts/check_platform_independence.py` scans `agents/**/*.json`, and a promoted case's evidence artefact lands exactly there. The test shop's own Terms & Conditions read:

> *"These terms apply to every purchase made from **bagisto**."*

That is the shop's own registered name, written by the merchant, on their own policy page. And **every product URL is `http://bagisto.test/…`**, which is the storefront's hostname. So a policy turn, a product turn and a search turn all carry a platform name:

```
✘ PLATFORM INDEPENDENCE VIOLATED
  agents/care/.../fixtures/graded/57a2f7c6….json:23
```

**Not one turn on that shop was promotable**, and promotion was made to refuse rather than let `make arch` go red.

### Why this is not the failure rule 1 exists to catch

[AGENTS.md](../../../AGENTS.md) rule 1 protects one claim: *the core does not know which platforms exist.* What makes that claim false is **behaviour** — a branch on a platform name, an adapter imported outside `packages/neura-adapters/`, a configuration key that names a shop system.

`check_platform_independence.py` already draws this distinction and says so in its own docstring:

> *"Comments and docstrings are excluded. The rule protects against platform-specific **behaviour**, and prose cannot contain behaviour."*

It even strips string literals from Python for the same reason — *"a platform name inside a runtime string would be data rather than a structural dependency."*

**A merchant's returns policy is prose by exactly that test.** It is not our text, it is not executable, and nothing branches on it. The check was applying a rule about our code to a file containing somebody else's words, and reaching the wrong answer for a defensible reason: it had never had to distinguish *our* JSON from *captured* JSON, because until ADR-0034 there was no captured JSON.

### What the alternative would have cost

**Keep refusing** was the fail-closed position and it held for a few hours. It is not survivable: a real merchant's URLs and T&Cs would not name a commerce platform, so the rule blocks **validation on the only shop this project has** while permitting the production case it was never aimed at. [E1](../../open-questions.md) is waiting on exactly that validation.

**Strip platform names from evidence** was rejected outright. It changes what the agent replays, so a promoted case would assert against evidence no human approved — the precise defect [ADR-0034](0034-a-promoted-case-carries-the-shop-it-was-graded-on.md) exists to remove.

## Decision

> **Automatically captured, content-addressed replay evidence under `agents/*/src/*/evals/fixtures/graded/*.json` is merchant data, not application behaviour. Platform names occurring inside its free-text values or URLs do not violate platform independence.**

### 1. The exemption is segment-exact, and there is exactly one of it

`agents/<agent>/src/<package>/evals/fixtures/graded/<file>.json` — eight path segments, matched one at a time by `is_graded_evidence()`.

**It was written as an `fnmatch` glob first, and that was wrong.** `fnmatch` lets `*` cross `/`, while `Path.glob` does not — so the exemption in one script and the structural check in the other described **different sets of files**, with the exemption the wider of the two. `agents/care/**extra**/src/…`, `…/graded/**nested**/a.json` and `agents/care/src/**x/y**/…` were all exempt from the text scan and checked by nothing. **That is the one relationship between these two checks that must never hold**, and it was invisible from either script alone.

Both now import the same function, so the sets are identical by construction rather than by two authors agreeing. Pinned three ways: negative cases for each over-match, and a test comparing the two sets over the repository as it actually is.

**Everything else stays in scope, and the list is worth stating because each entry is a way this could have been over-applied:**

| still scanned | why it must be |
|:--|:--|
| Python | where a branch on a platform would live |
| Prompts | a prompt naming a platform is behaviour written in English |
| YAML datasets | hand-written, including `graded.yaml` itself |
| Hand-written fixtures — `store.json` and friends | ours, not a merchant's |
| Configuration | a platform-named key is coupling |
| **Every other JSON**, anywhere | including other files in the same `fixtures/` directory |

### 2. Rule 1 is unchanged, and this ADR must not be read as narrowing it

No platform-specific branching, adapter, import or configuration may exist outside `packages/neura-adapters/`. Nothing here permits any of those, in an evidence file or anywhere else — **the exemption is from a textual scan of merchant-authored values, and from nothing else.** An artefact containing a `platform` *field* is still refused, by §3.

### 3. The exemption is paid for by a structural check

`scripts/check_graded_evidence.py`, run by `make arch` beside the platform check because the two are one decision. Every artefact must satisfy, or the build fails:

| requirement | what it prevents |
|:--|:--|
| `schema_version` present, ≥ 2, ≤ what this code replays | a file nobody can replay, or one predating the `pii_output` flag |
| **filename, embedded and recomputed hashes all agree** | a renamed, mis-cited or hand-edited artefact |
| no `raw` field, at any depth | a commerce platform's own payload — whose *field names* would be genuine coupling |
| no `platform`, `tenant_id`, `neura_id`, `synced_at` | provenance this side assigns and never accepts from a file |
| no `store_id` | ADR-0034 §7 |
| no credential-shaped value | a secret in git |
| `pii_output` is `False` | a turn that read customer data |
| only known top-level keys | a field nobody thought about being written to a repository |

**Textual where it was, structural where it now is — and structural is the harder bar.** A platform name may appear in a merchant's policy text; a platform *field* may not appear at all.

### 4. Promotion no longer refuses on platform names

The refusal added on 2026-09-06 existed only because these files were in the text scan's scope. It is removed with its reason. Every other promotion refusal — no evidence, empty evidence, `pii_output`, credentials, a shop that has moved, an already-promoted turn — is untouched.

## Consequences

**Good.** The promotion loop can be exercised on the Bagisto harness, which is the only shop this project has and the thing [E1](../../open-questions.md) has been unable to move without. The first promoted case now lives in the repository, its artefact beside it, and `make arch` is green.

**Costs, accepted.**

- **One directory is no longer text-scanned.** Mitigated by §3 and bounded by §1, and the risk it carries — a platform name in a merchant's words — is not the risk rule 1 is about.
- **A second checker to keep working.** A structural check that silently stopped finding artefacts would be `tool_selection_accuracy`'s 2026-08-27 failure again, so it prints the count it scanned.
- **The distinction now has to be understood by whoever reads it.** "Merchant data, not behaviour" is a judgement, and a future contributor could stretch it. §1's table exists to make stretching visible.

**Unchanged.** Rule 1. `import-linter`'s seven contracts. The adapter boundary. CARE's and SELL's prompts, graphs and behaviour — this ADR touches a checker and a promotion refusal, and nothing a shopper can reach.

## Alternatives considered

**Keep refusing to promote evidence containing a platform name.** Fail-closed and correct on the day. Rejected: it blocks validation on the only available shop while permitting the production case the rule was never aimed at, and E1 is waiting on that validation.

**Strip or redact platform names from captured evidence.** Rejected: it changes what the agent replays, so a promoted case would assert against evidence no human approved — ADR-0034's founding defect, reintroduced as a fix.

**Exempt the whole `fixtures/` directory.** Rejected: `store.json` and the hand-written overlays are *ours*, and a platform name in one of them would be exactly the coupling rule 1 catches.

**Stop scanning `.json` altogether.** Rejected as far too wide — configuration is JSON, and a platform-named key in configuration is coupling.
