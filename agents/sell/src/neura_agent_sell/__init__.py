"""NEURA-SELL — agent-readiness, and the second sellable agent here.

Designed in [`docs/agents/sell.md`](../../../../docs/agents/sell.md) and decided
in ADR-0023. Read that first: this package is being built in the order that
document recommends, and it is **incomplete on purpose**.

**SELL is one product with three surfaces, and only one of them is an agent.**
That is the fact that shapes everything else here:

    recommendation   a shopper, in the widget      a graph, our model     NOT BUILT
    MCP server       someone else's AI agent       no graph, no model     NOT BUILT
    product feed     crawlers, answer engines      no graph, no model     ← building

Only the first is an *Agent* as the glossary defines one. The other two have no
nodes, no prompts and no LLM call of ours anywhere in them. The manifest and the
entitlement gate all three, which is what makes them one sellable product — but
calling three surfaces "a graph" would be a tidy fiction, and `agents/README.md`
already refuses the same fiction for GUARD.

**The safety argument is therefore not CARE's, and must not be borrowed by
habit.** CARE's is *a persuaded model achieves nothing, because no tool that
changes a store was ever registered*. On the feed and over MCP there is **no
model of ours to persuade** — what remains is read-only data, the policy engine,
tenant isolation, and nothing else.

  scope     read-only. Grounded recommendation, an MCP server over the
            catalogue, a machine-readable product feed.
  excluded  agent-facing checkout and cart recovery — both writes, blocked by
            ADR-0010 until the approval queue exists. **Not re-openable here:**
            reopening them is a superseding ADR, not a pull request.
  writes    NONE, on every surface.

**Nothing in this package requires a change to `neura-domain`, the adapter
protocol or the conformance suite.** A store already conformant for CARE is
already conformant for SELL — verified against `neura_domain.Capability` rather
than assumed, and it is the asymmetry against MIND that decided agent #2.

HARD RULE: this package must never import another agent. The catalogue tools
here will be near-copies of CARE's, and that duplication is deliberate and
recorded as open question **A12** — copy now, extract at the third agent.
"""

from neura_agent_sell.manifest import MANIFEST, AgentManifest

__all__ = ["MANIFEST", "AgentManifest"]
