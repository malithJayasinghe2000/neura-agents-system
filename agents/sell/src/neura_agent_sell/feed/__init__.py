"""The product feed — SELL's third surface, and the first one built.

**No graph, no prompt, no model call.** A crawler asks for a document and gets
one; nothing here reasons about anything. That is why it is built first: it is
deterministic, testable without a model server, and costs nothing to run.

    publishable.py   what may leave the building — an allowlist, as a TYPE
    document.py      the format-neutral document, and the timestamp rule
    canonical.py     renderer 1 — our own model, complete
    jsonld.py        renderer 2 — Schema.org, understood by answer engines

The pipeline, and each arrow narrows what is possible:

    [Product]  ──publishable()──►  [PublishableProduct]  ──build()──►  FeedDocument
                                                                            │
                                                            ┌───────────────┴──────────────┐
                                                            ▼                              ▼
                                                   canonical.render()             jsonld.render()

A renderer never sees a `Product`, so it cannot publish `raw`, `platform`,
`tenant_id` or `neura_id` — not because it is careful, but because it was never
handed them. Adding a canonical field publishes nothing until somebody adds it
to `publishable.py` on purpose.

**Exposure is ADR-0024**, and is a separate concern from everything in this
package: opt-in, off by default, addressed by a hashed rotatable secret. Nothing
here decides who may read a document; these modules decide only what a document
may say.
"""

from neura_agent_sell.feed import canonical, jsonld
from neura_agent_sell.feed.document import FeedDocument, build
from neura_agent_sell.feed.publishable import (
    PublishableProduct,
    PublishableVariant,
    is_publishable,
    publishable,
)

__all__ = [
    "FeedDocument",
    "PublishableProduct",
    "PublishableVariant",
    "build",
    "canonical",
    "is_publishable",
    "jsonld",
    "publishable",
]
