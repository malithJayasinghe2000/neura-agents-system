# Contributing

Conventions and coding rules live in [`AGENTS.md`](AGENTS.md). This file covers process.

---

## Before you start

1. Read [`docs/glossary.md`](docs/glossary.md) — terms have exactly one meaning here.
2. Read [`AGENTS.md`](AGENTS.md) — especially the four rules.
3. Check [`docs/architecture/adr/`](docs/architecture/adr/) — the decision you are about to relitigate may already be recorded, with its downsides acknowledged.

---

## Workflow

```bash
git checkout -b feat/short-description     # feat/ fix/ docs/ refactor/ chore/
make check                                 # before every push
```

**Commits** follow [Conventional Commits](https://www.conventionalcommits.org/) — `feat(commerce): add capability negotiation`. Scope is the package name.

**Small PRs.** One concern each. A PR touching five packages usually should have been five PRs.

---

## PR checklist

- [ ] `make check` passes (lint, types, tests, evals)
- [ ] No commerce-platform name outside `packages/neura-adapters/`
- [ ] New tools declare `requires`, `side_effect`, `scopes`, `pii_output`
- [ ] Behaviour changes (prompts, graph, tools, model config) have eval results in the PR body
- [ ] Injection resistance still **1.00**
- [ ] New tables carry `tenant_id` **and** an RLS policy
- [ ] Migration is reversible, or the PR explains why it cannot be
- [ ] Docs updated in the same PR — not "later"
- [ ] Significant decisions recorded as an ADR

---

## Writing an ADR

Any decision that is expensive to reverse, that a future reader would question, or where you rejected a reasonable alternative.

Copy the shape of an existing one: **Context · Decision · Consequences · Alternatives considered**.

Two rules:

- **State the bad consequences.** An ADR listing only benefits is marketing. The "Bad / accepted" section is the one people actually return to read.
- **ADRs are immutable.** To reverse one, write a new ADR that supersedes it and mark the old one `Superseded by ADR-00XX`. Never edit history — future readers need to see why we once thought otherwise.

---

## Documentation

Docs are part of the deliverable, not an afterthought. The test in [`docs/README.md`](docs/README.md) is that someone who has never seen the project can answer *"who buys this, what does the MVP do, and how do I integrate a new store?"* from `docs/` alone.

When code and docs disagree, that is a bug — fix both.

---

## Reporting a security issue

Do not open a public issue. Contact the maintainer directly.

Particularly interested in: prompt injections that reach a tool, cross-tenant data access, ownership-verification bypasses, and PII appearing in logs or traces.
