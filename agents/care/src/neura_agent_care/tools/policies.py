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

import math
import re

from neura_agent_care.tools.render import policy_evidence
from neura_agent_core.tools import ToolContext, tool
from neura_core import get_logger
from neura_domain import Capability, Policy, PolicyKind

log = get_logger(__name__)

#: Two pages is usually the honest answer to "how do returns work?" — the
#: returns page and the refund page often split the rule between them.
MAX_POLICIES = 2

#: A page whose *kind* matches the question gets this much, once — not once per
#: matching term. Kind is one signal that the page is on-topic, not a count of
#: how on-topic it is, and scoring it per term let a single well-known word bury
#: a page that answered the question.
#:
#: Deliberately small relative to a rare-word match. Measured: "do you take cash
#: on delivery" scored the shipping page 21 on the strength of `delivery` and
#: never returned the payment page, which is the only page in the store
#: containing the words "cash on delivery". A kind is a hint; the merchant's own
#: distinctive vocabulary is evidence.
KIND_BOOST = 2.5

#: A word in the page's *title* counts for more than the same word in its body.
#: The title is the merchant's own one-line label for the page.
TITLE_WEIGHT = 3.0

#: Words too common to carry any signal about which page is meant. Kept to
#: genuine function words — a stop list that grows to include domain nouns is
#: how a search silently stops being able to find things.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "by",
        "can",
        "could",
        "do",
        "does",
        "doing",
        "for",
        "from",
        "get",
        "got",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "much",
        "my",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)

#: Words that reliably indicate a policy kind. Kept small and unambiguous: a
#: term that could mean two kinds is worse than no term, because it makes the
#: match confident rather than absent.
#:
#: There is deliberately no entry for ``PolicyKind.OTHER``. It is the catch-all —
#: on the test shop it holds About Us, Customer Service and Payment Policy, which
#: have nothing in common — so no term could indicate it. Those pages are found
#: by their own vocabulary instead, which is why rare-word matching had to carry
#: real weight before they were reachable at all.
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

    idf = _idf(policies)
    scored = sorted(((_score(p, query, idf), p) for p in policies), key=lambda s: -s[0])
    best = [policy for score, policy in scored if score > 0][:MAX_POLICIES]

    if not best:
        # Titles, not kinds. Half this store's pages are `other`, so a list of
        # kinds reads "returns, shipping, other, other, other" and tells the
        # composer nothing it can offer the shopper. The merchant's own page
        # names are the useful answer to "what can you tell me about?".
        available = ", ".join(sorted(p.title for p in policies))
        return (
            f"No policy page matches {topic!r}. This store publishes these pages: "
            f"{available}. Do not answer from general knowledge about how shops usually work."
        )

    log.info(
        "policy_lookup",
        tenant_id=ctx.tenant_id,
        topic=query,
        matched=[p.kind.value for p in best],
    )
    return "\n\n".join(policy_evidence(policy) for policy in best)


def _stem(word: str) -> str:
    """Crude, deliberate suffix stripping so "emails" finds "email".

    Not a linguistic stemmer. It exists because the merchant writes "Email is
    usually answered within one working day" and the shopper types "how quickly
    do you answer emails", and an exact-match search calls that no match at all.

    Applied to the query, the page and the kind terms alike — a stemmer used on
    one side of a comparison and not the other is worse than none.
    """
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "ies":
                return word[:-3] + "y"
            if suffix == "s" and word.endswith("ss"):
                continue
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    """The words in a piece of text that could identify a page."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(w) for w in words if w not in _STOPWORDS and len(w) > 1}


def _idf(policies: list[Policy]) -> dict[str, float]:
    """How much each word narrows the field, over this store's own pages.

    The point of weighting by rarity: on a clothing store "delivery" appears on
    half the pages and says almost nothing about which one is meant, while
    "cash" appears on exactly one and says everything. A flat count treats the
    two alike, which is how a question about paying cash on delivery came back
    with the shipping page and nothing else.

    Computed per store, not hard-coded, because which words are distinctive is a
    property of the merchant's own writing and no two stores write alike.
    """
    total = len(policies)
    seen: dict[str, int] = {}
    for policy in policies:
        for token in _tokens(policy.title + " " + policy.body):
            seen[token] = seen.get(token, 0) + 1
    # +1 inside the log keeps every idf positive: a word on every page scores
    # low, never zero, so a page matching many common words still beats one
    # matching none.
    return {token: math.log(1 + total / count) for token, count in seen.items()}


def _score(policy: Policy, query: str, idf: dict[str, float]) -> float:
    """How well one policy answers this topic. Higher is better, 0 means no match."""
    asked = _tokens(query)
    title = _tokens(policy.title)
    body = _tokens(policy.body)

    score = 0.0
    for token in asked:
        weight = idf.get(token, 0.0)
        if token in title:
            score += TITLE_WEIGHT * weight
        elif token in body:
            score += weight

    # The kind hint, once. A multi-word term counts when all of its words are in
    # the question, adjacent or not — the shopper writes "can I send these back",
    # and requiring "send back" to be contiguous loses it.
    for term in _KIND_TERMS.get(policy.kind, frozenset()):
        if {_stem(w) for w in term.split()} <= asked:
            score += KIND_BOOST
            break

    return score
