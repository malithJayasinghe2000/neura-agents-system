"""NEURA-CARE — the customer experience agent, and the first sellable agent here.

MVP scope, cut deliberately narrow (blueprint-v2 §5.1, agent-runtime.md):

  intents   order status · product Q&A · returns and shipping policy
  tools     get_order_status · find_orders_for_customer · search_products ·
            get_product_details · check_stock · search_policies · escalate_to_human
  writes    NONE. Every tool is READ, and the registry refuses to register
            anything else while the approval queue does not exist (ADR-0010).
            The agent cannot change a store — a security property, not a
            limitation to apologise for.

The parts:

  manifest.py      identity: the capabilities it needs, its scopes, its routes
  graph.py         the flow — six CARE nodes, six inherited from the engine
  nodes/           route · plan · triage · compose · respond · decline
  runtime.py       how one conversation is equipped
  serving.py       how a request becomes a turn (the API resolves this)
  tools/           the seven above, each adapter-backed
  prompts/         versioned files, content-hashed, never inline strings
  evals/           the golden dataset, and the target that runs CARE against it

**What CARE does not contain is the point.** No policy engine, no audit log, no
checkpointer, no capability filtering, no ownership enforcement — those live in
``neura-agent-core``, are inherited by every agent, and could not be weakened
from here. Agent #2 supplies the same parts and nothing else (agent-runtime.md
§7).

``guard`` and ``blocked`` arrived in milestone 1.12 and are inherited, not
written here: five deterministic injection rules and reversible PII tokenisation,
no model and no threshold (ADR-0011). ``graph.py`` explains why injection
resistance was 1.00 *before* they existed and must never be credited to them.

HARD RULE: this package must never import another agent. Cross-agent
communication goes through the event bus (Phase 3), never a direct import.
"""

from neura_agent_care.graph import build_graph, compile_graph
from neura_agent_care.manifest import MANIFEST, AgentManifest
from neura_agent_care.prompts import REVISION as PROMPT_REVISION
from neura_agent_care.runtime import build_runtime
from neura_agent_care.serving import CareRunner, build_runner
from neura_agent_care.tools import CARE_TOOLS, build_registry

__all__ = [
    "CARE_TOOLS",
    "MANIFEST",
    "PROMPT_REVISION",
    "AgentManifest",
    "CareRunner",
    "build_graph",
    "build_registry",
    "build_runner",
    "build_runtime",
    "compile_graph",
]
