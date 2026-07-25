"""NEURA-CARE — customer experience agent.

The graph, tools and prompts are NOT YET IMPLEMENTED. Phase 1 milestone 1.11 —
see docs/roadmap.md. The manifest below is real and is what the API discovers at
startup.

MVP scope (docs/architecture/agent-runtime.md):

  intents   order status · product Q&A · returns and shipping policy
  tools     get_order_status · find_orders_for_customer · search_products ·
            get_product_details · check_stock · search_policies · escalate_to_human
  writes    NONE. Every tool is READ. The agent cannot modify a store, which is a
            deliberate security property — see ADR-0010.

Planned layout, all five parts:

  manifest.py      ✅ done
  graph.py         ⬜ the flow
  nodes/           ⬜ steps unique to CARE
  tools/           ⬜ the seven tools above
  prompts/         ⬜ versioned files, never inline strings
  evals/datasets/  ⬜ golden cases — no agent ships without one

HARD RULE: this package must never import another agent. Cross-agent
communication goes through the event bus (Phase 3), never a direct import.
"""

from neura_agent_care.manifest import MANIFEST, AgentManifest

__all__ = ["MANIFEST", "AgentManifest"]
