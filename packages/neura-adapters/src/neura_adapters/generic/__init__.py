"""Tier 2 — the Generic Commerce Interface.

A store implements nine read-only endpoints and a signed webhook; this package
consumes them. It is the MVP integration path because it is the only one that
serves a custom or newly built store — nobody will ever write a native adapter
for a shop that exists once
(docs/architecture/adr/0009-generic-commerce-interface.md).

Five parts:

* ``adapter`` — ``GenericAdapter``, the ``CommerceAdapter`` implementation.
* ``wire`` — the mapping between a store's JSON and the canonical model. The
  spec *is* the canonical model, so this is thin by design.
* ``webhooks`` — HMAC verification for store-to-us change notifications.
* ``spec`` / ``cli`` — the published OpenAPI document and the conformance tool a
  merchant's developer runs against their own endpoint.
* ``teacher`` — what the developer MCP server teaches a developer's AI tool: the
  format, a sample for every answer, and the rules (ADR-0053).
"""

from neura_adapters.generic.adapter import SPEC_CAPABILITIES, GenericAdapter
from neura_adapters.generic.client import GenericClient
from neura_adapters.generic.spec import build_openapi, render
from neura_adapters.generic.webhooks import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    WebhookEvent,
    WebhookSignatureError,
)
from neura_adapters.generic.wire import SPEC_VERSION

__all__ = [
    "SIGNATURE_HEADER",
    "SPEC_CAPABILITIES",
    "SPEC_VERSION",
    "TIMESTAMP_HEADER",
    "GenericAdapter",
    "GenericClient",
    "WebhookEvent",
    "WebhookSignatureError",
    "build_openapi",
    "render",
]
