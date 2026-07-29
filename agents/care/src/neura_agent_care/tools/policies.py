"""Policy lookups — returns, shipping, refunds, warranty, payment, privacy.

The third of CARE's three intents, and the one where being wrong is quietest.
Nobody notices immediately when an agent states a 45-day returns window that the
merchant's page says is 30 — the shopper finds out at the point of return, and
by then it is the merchant's problem to explain.

So the selection here is deliberately dull: kind matching plus keyword overlap,
scored in code. There is no model call in this tool. A cleverer selector would
occasionally pick a better page and would occasionally pick a confident wrong
one, and the second failure costs more than the first gains.
"""

from __future__ import annotations

from neura_agent_care.tools.render import policy_evidence
from neura_agent_core.tools import ToolContext, tool
from neura_core import get_logger
from neura_domain import Capability, Policy, PolicyKind

log = get_logger(__name__)

#: Two pages is usually the honest answer to "how do returns work?" — the
#: returns page and the refund page often split the rule between them.
MAX_POLICIES = 2

#: Words that reliably indicate a policy kind. Kept small and unambiguous: a
#: term that could mean two kinds is worse than no term, because it makes the
#: match confident rather than absent.
_KIND_TERMS: dict[PolicyKind, frozenset[str]] = {
    PolicyKind.RETURNS: frozenset(
        {
            "return",
            "returns",
            "returning",
            "refund",
            "refunds",
            "exchange",
            "exchanges",
            "send back",
        }
    ),
    PolicyKind.SHIPPING: frozenset(
        {"shipping", "delivery", "deliver", "postage", "dispatch", "courier", "tracking", "arrive"}
    ),
    PolicyKind.WARRANTY: frozenset({"warranty", "guarantee", "faulty", "broken", "defective"}),
    PolicyKind.PRIVACY: frozenset({"privacy", "data", "gdpr", "personal information", "cookies"}),
    PolicyKind.TERMS: frozenset({"terms", "conditions", "payment", "pay", "card", "checkout"}),
}


@tool(
    name="search_policies",
    description=(
        "Look up the store's own written policies on returns, refunds, shipping, "
        "warranty, payment or privacy. Use for any question about how the store "
        "operates rather than about a specific order or product."
    ),
    requires=[Capability.POLICY_READ],
    scopes=["care:policies:read"],
)
async def search_policies(topic: str, ctx: ToolContext) -> str:
    """The store's policy text, verbatim.

    Verbatim matters. The value of this tool is that the merchant's own words
    reach the composer, so a claim about a returns window can be checked against
    the page it came from rather than against a summary of it.
    """
    query = topic.strip().lower()
    if not query:
        return "No topic was given, so no policy was looked up."

    policies = [p for p in await ctx.adapter.get_policies() if p.body.strip()]

    if not policies:
        # An empty body is a data problem, not a policy the shopper should be
        # told about — the 1.9 lesson, one layer up: an entity with nothing in it
        # renders to something structurally valid and semantically empty.
        return (
            "This store has published no policy text. Do not describe its policies "
            "from general knowledge — offer to pass the shopper to a colleague."
        )

    ranked = sorted(policies, key=lambda p: _score(p, query), reverse=True)
    best = [p for p in ranked if _score(p, query) > 0][:MAX_POLICIES]

    if not best:
        available = ", ".join(sorted({p.kind.value for p in policies}))
        return (
            f"No policy page matches {topic!r}. This store publishes policies on: "
            f"{available}. Do not answer from general knowledge about how shops usually work."
        )

    log.info(
        "policy_lookup",
        tenant_id=ctx.tenant_id,
        topic=query,
        matched=[p.kind.value for p in best],
    )
    return "\n\n".join(policy_evidence(policy) for policy in best)


def _score(policy: Policy, query: str) -> int:
    """How well one policy answers this topic. Higher is better, 0 means no match.

    Kind terms weigh heaviest because they are the reliable signal — "refund"
    means the returns page whatever else the sentence contains. Title and body
    overlap break ties between two pages of the same kind.
    """
    score = 0

    for term in _KIND_TERMS.get(policy.kind, frozenset()):
        if term in query:
            score += 10

    title_words = set(policy.title.lower().split())
    query_words = set(query.split())
    score += 3 * len(title_words & query_words)

    body = policy.body.lower()
    # Only distinctive words. Matching "the" in a policy body says nothing, and
    # counting it would make every page score alike.
    score += sum(1 for word in query_words if len(word) > 4 and word in body)

    return score
