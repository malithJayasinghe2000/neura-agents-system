"""NEURA-GROW — the marketing agent. Designed in docs/agents/grow.md; ADR-0064.

**Its first surface has no chat.** *Missing from your pages* is a nightly job
that reads the shop's chats and a dashboard page that shows the questions at
least two shoppers asked that the shop's data could not answer. No shopper ever
talks to GROW, so it has no graph and no runner, and its manifest says so
(``chat = False``).

  scope     read-only. Reads NEURA's own record of the shop's chats.
  excluded  writing to the shop (ADR-0010), sending anything to anyone, and
            every other GROW idea (R36): each is its own design.
  writes    rows in NEURA's own tables only, never the shop.

HARD RULE: this package must never import another agent.
"""

from neura_agent_grow.manifest import MANIFEST, AgentManifest

__all__ = ["MANIFEST", "AgentManifest"]
