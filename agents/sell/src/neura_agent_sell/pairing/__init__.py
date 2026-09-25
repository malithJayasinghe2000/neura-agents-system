"""SELL's fourth surface: what goes with a product ([ADR-0040]).

A page sends product ids and gets back at most two complementary products. It
has **no nodes, no prompts and no LLM call of ours in it**, which puts it beside
the MCP server and the product feed rather than beside the recommendation
widget — and means a persuaded model is not part of its threat model, because
there is no model to persuade.

The safety argument is the policy engine and tenant isolation, exactly as
``docs/CLAUDE.md §5`` requires for the other two model-free surfaces.
"""

from neura_agent_sell.pairing.orchestrate import Pairing, suggest

__all__ = ["Pairing", "suggest"]
