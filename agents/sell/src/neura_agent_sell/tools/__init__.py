"""NEURA-SELL's tool set — five tools, every one of them read-only.

The list from `docs/agents/sell.md` §3.1, in full:

    search_products       PRODUCT_SEARCH     find candidates for a need
    get_product_details   PRODUCT_READ       expand one candidate
    check_stock           INVENTORY_READ     confirm it can actually be bought
    list_categories       CATEGORY_READ      what this store carries at all
    escalate_to_human     —                  always available

**Nothing here can change a store.** Every tool declares ``side_effect=READ``,
and the registry refuses to register anything else while the approval queue does
not exist (ADR-0010). A checkout tool is not disabled or hidden — it does not
exist, so the most persuasive injection imaginable has nothing to invoke.

**Not one of these reads a person.** `pii_output` is `False` on every tool
because a catalogue is public, and that is the honest declaration rather than a
convenient one — SELL's conversational surface never touches a customer record,
so its entire PII surface is the shopper's own typed message. Over-declaring
would evict a public search from the semantic cache for nothing and make the
flag meaningless where it actually matters, which is CARE's order tools.

## Why these are near-copies of CARE's, deliberately

An agent may never import another agent (AGENTS.md, and the architecture test
that enforces it). So `get_product_details` and `check_stock` are written again
here rather than shared.

That duplication is **open question A12**, recorded rather than resolved. A
generic catalogue tool does not name an agent, so `neura-agent-core` could
legitimately hold one — but the scopes are agent-prefixed, so extraction means
parameterising scope construction against a sample size of two, which produces
an abstraction shaped by its only two examples. The recommendation is to copy
now and extract at the third agent.

They are also not identical, and the differences are the point: SELL searches to
build a *shortlist* rather than to answer about a named product, so its result
carries the attributes a suitability claim can be attributed to.
"""

from __future__ import annotations

from neura_agent_core.tools import ToolRegistry, ToolSpec
from neura_agent_sell.tools.catalogue import (
    check_stock,
    get_product_details,
    list_categories,
    search_products,
)
from neura_agent_sell.tools.handover import (
    HANDOVER_REQUESTED,
    escalate_to_human,
    was_requested,
)

#: Every tool SELL ships, in the order of `sell.md` §3.1.
#:
#: A store that declares fewer capabilities simply sees fewer of them — the
#: registry filters per conversation, and a tool the store cannot satisfy is
#: never put in a model's context at all. That is stronger than refusing the
#: call afterwards: you cannot talk a model into invoking a tool it was never
#: shown.
SELL_TOOLS: tuple[ToolSpec, ...] = (
    search_products,
    get_product_details,
    check_stock,
    list_categories,
    escalate_to_human,
)

#: The scopes SELL's tools require, together. Must be a subset of what the
#: manifest declares, or a correctly-provisioned key is refused at the policy
#: engine's third check while looking perfectly configured — a failure that
#: reads as "the agent never calls any tool". Asserted by a test.
TOOL_SCOPES = frozenset(scope for spec in SELL_TOOLS for scope in spec.scopes)

#: What an *external* AI agent may reach over MCP (`sell.md` §6.2).
#:
#: `escalate_to_human` is deliberately absent. There is no human in an MCP
#: session to escalate *to*, and a tool that files into a merchant's support
#: queue on a bot's say-so is a denial-of-service surface with a friendly name.
#:
#: An allowlist rather than a subtraction, so a tool added to `SELL_TOOLS` later
#: is **not** exposed to third parties until somebody names it here. The default
#: for a new tool is private.
MCP_TOOLS = frozenset(
    {
        search_products.name,
        get_product_details.name,
        check_stock.name,
        list_categories.name,
    }
)


def build_registry() -> ToolRegistry:
    """A registry holding SELL's tools.

    Built per process, not per conversation: registration is about what exists
    in this deployment. *Availability* — which of them a given caller may use —
    is decided per request by ``available_for(ctx)``.
    """
    return ToolRegistry(SELL_TOOLS)


__all__ = [
    "HANDOVER_REQUESTED",
    "MCP_TOOLS",
    "SELL_TOOLS",
    "TOOL_SCOPES",
    "build_registry",
    "check_stock",
    "escalate_to_human",
    "get_product_details",
    "list_categories",
    "search_products",
    "was_requested",
]
