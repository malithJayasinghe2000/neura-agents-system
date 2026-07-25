"""neura-commerce — adapter contract, capability negotiation, sync engine.

NOT YET IMPLEMENTED. Phase 1 milestones 1.5-1.8 — see docs/roadmap.md.

Design is settled in docs/architecture/commerce-integration.md and
docs/architecture/adr/0003-canonical-domain-model.md. The shape:

* ``CommerceAdapter`` protocol (a typing.Protocol, not an ABC — so a third party
  can implement one without importing from us), returning canonical models.
* Each adapter declares ``capabilities: frozenset[Capability]``; the agent's tool
  set is computed from that declaration, which is both the integration mechanism
  and a security control.
* ``AdapterError`` hierarchy so retry and escalation logic is written once.
* Sync engine: backfill -> incremental -> event-driven -> nightly reconcile.
  Idempotent, resumable, per-tenant rate limited.

HARD RULE: this package must never import neura_adapters. The core must not know
which platforms exist. Enforced by an import-linter contract in CI.
"""

__all__: list[str] = []
