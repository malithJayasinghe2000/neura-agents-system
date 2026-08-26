"""The format-neutral feed document.

One document, several renderings — [ADR-0023](../../../../../docs/architecture/adr/0023-sell-is-read-only-and-a-protocol-is-an-output-format.md)'s
central commitment, made concrete. Every renderer in this package takes a
:class:`FeedDocument` and nothing else, so adding a format is a new function
here and **never** a change to `neura-domain`, the adapter protocol, the sync
engine or a graph. A protocol dying costs one renderer.

## The timestamp rule, and why it is structural

> **The timestamp is the sync's, never the request's.**

A price carries a date or it is an offer with no date. Serving a document
stamped `now()` turns a week-old price into a fresh-looking one, and a merchant
finds out when a shopper arrives holding it.

The obvious implementation is a `generated_at` parameter with a comment saying
*please pass the sync time*. That comment is one hurried caching layer away from
`datetime.now(UTC)`, and the resulting document is indistinguishable from a
correct one — no error, no warning, just a lie with a plausible date on it.

So there is no parameter. :attr:`FeedDocument.synced_at` is **derived from the
products themselves** — the newest `synced_at` among them — and serve-time
cannot be passed in because there is nowhere to pass it. An old catalogue
reports an old date, which is the honest answer and the one a stale-content
check downstream can act on.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from neura_agent_sell.feed.publishable import PublishableProduct


class FeedDocument(BaseModel):
    """A tenant's publishable catalogue, before it is rendered as anything."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    products: list[PublishableProduct] = Field(default_factory=list)

    #: The store's own name, as the merchant configured it. Not the tenant id.
    store_name: str | None = None

    #: Whether availability was assertable when this document was built. Carried
    #: so a renderer does not have to infer it from every variant being ``None``
    #: — a catalogue that genuinely happens to be entirely out of stock would
    #: otherwise be read as a store with no inventory feed.
    availability_asserted: bool = False

    #: Set when the catalogue continues beyond this page. Rendered as a link so
    #: a crawler can follow it rather than assuming it has seen everything.
    next_cursor: str | None = None

    @property
    def synced_at(self) -> datetime | None:
        """When the freshest thing in this document was last read from the store.

        ``None`` only for an empty document, where there is nothing to date and
        claiming a date would be inventing one.
        """
        return max((p.synced_at for p in self.products), default=None)

    @property
    def is_empty(self) -> bool:
        return not self.products


def build(
    products: list[PublishableProduct],
    *,
    store_name: str | None = None,
    availability_asserted: bool = False,
    next_cursor: str | None = None,
) -> FeedDocument:
    """Assemble a document. Deliberately dull, and takes no clock."""
    return FeedDocument(
        products=products,
        store_name=store_name,
        availability_asserted=availability_asserted,
        next_cursor=next_cursor,
    )


__all__ = ["FeedDocument", "build"]
