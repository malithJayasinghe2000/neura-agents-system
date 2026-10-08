"""The OpenAPI 3.1 document for the Generic Commerce Interface.

**Generated, never hand-written.** Every schema comes from the same Pydantic
models the agent reasons over, minus the provenance fields only we can know
(``wire.PROVENANCE_FIELDS``). A hand-maintained spec drifts from the code within
weeks, and the first person to notice is a merchant's developer who has already
implemented the wrong thing.

OpenAPI 3.1 specifically, because its schema dialect *is* JSON Schema 2020-12 —
which is what Pydantic emits. Any other version would need a lossy translation
step, and lossy is how a published contract becomes wrong.

Regenerate with ``make spec``; a unit test fails if the committed document and
the models disagree.
"""

from __future__ import annotations

import json
from typing import Any

from neura_adapters.generic.adapter import (
    PATH_CATEGORIES,
    PATH_CUSTOMER,
    PATH_HEALTH,
    PATH_INVENTORY,
    PATH_ORDER,
    PATH_ORDERS,
    PATH_POLICIES,
    PATH_PRODUCT,
    PATH_PRODUCTS,
)
from neura_adapters.generic.webhooks import (
    KNOWN_EVENTS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    WebhookEvent,
)
from neura_adapters.generic.wire import PROVENANCE_FIELDS, SPEC_VERSION
from neura_commerce import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neura_domain import (
    Capability,
    Category,
    Customer,
    InventoryLevel,
    Order,
    Policy,
    Product,
)

REF_TEMPLATE = "#/components/schemas/{model}"

_ENTITIES = (Product, Order, Customer, Category, Policy)

_DESCRIPTION = """
The read-only interface a store implements to be served by a Neura agent.

Nine GET endpoints and one outbound webhook. No writes, no state, no OAuth
flow — a bearer token issued per store and JSON that matches these schemas.

Three rules worth reading before implementing:

* **Cursor pagination, never offsets.** `next_cursor` is opaque to us; encode
  whatever you like in it. `null` means the last page. Offsets skip and repeat
  rows while a merchant edits the catalogue mid-crawl.
* **`updated_since` is optional.** If you cannot filter by timestamp, omit
  `sync.incremental` from the capabilities in `/health` and you will be
  full-synced instead. Declaring it and ignoring it is the one failure mode
  that is worse than not supporting it.
* **Status fields use the canonical vocabulary in these schemas**, not your
  platform's. An unrecognised value is read as `unknown`, which is a worse
  answer for your customers than a mapped one.

The shop owner checks an implementation in their NEURA dashboard and sends you
the full result. It reports exactly what is wrong and where.
""".strip()


def build_openapi() -> dict[str, Any]:
    """The complete OpenAPI 3.1 document."""
    schemas: dict[str, Any] = {}

    for model in _ENTITIES:
        schemas[model.__name__] = _entity_schema(model, schemas)
    schemas[InventoryLevel.__name__] = _collect(InventoryLevel, schemas)
    schemas[WebhookEvent.__name__] = _collect(WebhookEvent, schemas)

    schemas["Health"] = _health_schema()
    schemas["Error"] = _error_schema()
    for model in _ENTITIES:
        if model in (Product, Order):
            schemas[f"{model.__name__}Page"] = _page_schema(model.__name__)

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Neura Generic Commerce Interface",
            "version": SPEC_VERSION,
            "summary": "Read-only commerce data, in one canonical vocabulary.",
            "description": _DESCRIPTION,
        },
        "servers": [
            {
                "url": "https://{store}/neura/v1",
                "variables": {"store": {"default": "store.example.com"}},
            }
        ],
        "security": [{"bearerAuth": []}],
        "tags": [
            {"name": "connectivity"},
            {"name": "catalogue"},
            {"name": "orders"},
            {"name": "customers"},
            {"name": "content"},
        ],
        "paths": _paths(),
        "webhooks": _webhooks(),
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "A token we issue per store. Every endpoint except /health "
                        "must reject a request without it — these endpoints expose "
                        "customer and order data."
                    ),
                }
            },
            "schemas": schemas,
        },
    }


# ── Schemas ──────────────────────────────────────────────────────────────────


def _collect(model: type[Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """One model's schema, with its nested definitions hoisted into components."""
    schema: dict[str, Any] = model.model_json_schema(
        ref_template=REF_TEMPLATE, mode="serialization"
    )
    for name, definition in schema.pop("$defs", {}).items():
        schemas.setdefault(name, _relax(definition))
    return _relax(schema)


def _relax(schema: dict[str, Any]) -> dict[str, Any]:
    """Allow fields we do not know about.

    Our own models forbid extra fields — inside this system an unexpected key is
    a bug. On the wire it is a store's own data, which we drop and keep in
    ``raw``. Publishing ``additionalProperties: false`` would make a store's
    internal field a spec violation, and a contract that breaks when the other
    side adds a field cannot be evolved by either of us.
    """
    schema.pop("additionalProperties", None)
    return schema


def _entity_schema(model: type[Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """A canonical entity as a store sends it — provenance removed.

    A store cannot know its tenant id or our internal id, and must not be
    trusted to assert which platform it is. Those fields are ours to fill in.
    """
    schema = _collect(model, schemas)
    for field in PROVENANCE_FIELDS:
        schema.get("properties", {}).pop(field, None)
    required = [name for name in schema.get("required", []) if name not in PROVENANCE_FIELDS]
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)
    return schema


def _page_schema(entity: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {"type": "array", "items": {"$ref": REF_TEMPLATE.format(model=entity)}},
            "next_cursor": {
                "type": ["string", "null"],
                "description": (
                    "Opaque. Pass it back as ?cursor= to get the next page; null on the "
                    "last page. It must advance — a cursor that repeats makes sync loop "
                    "forever."
                ),
            },
        },
    }


def _health_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["status", "spec_version", "platform", "capabilities"],
        "properties": {
            "status": {"const": "ok", "description": "Anything else is read as unhealthy."},
            "spec_version": {"type": "string", "examples": [SPEC_VERSION]},
            "platform": {"type": "string", "description": "Your store's own name. Informational."},
            "capabilities": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(c.value for c in Capability)},
                "description": (
                    "What this store supports. This single field decides which tools the "
                    "agent is given, so under-declaring costs a feature while "
                    "over-declaring produces tools that fail in front of a customer. "
                    "Declare only what you have implemented."
                ),
            },
            "detail": {"type": ["string", "null"]},
        },
    }


def _error_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"error": {"type": "string"}},
    }


# ── Paths ────────────────────────────────────────────────────────────────────


def _ok(schema_ref: str, description: str = "Success") -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {"schema": {"$ref": REF_TEMPLATE.format(model=schema_ref)}}
        },
    }


def _ok_array(schema_ref: str) -> dict[str, Any]:
    return {
        "description": "Success",
        "content": {
            "application/json": {
                "schema": {
                    "type": "array",
                    "items": {"$ref": REF_TEMPLATE.format(model=schema_ref)},
                }
            }
        },
    }


_NOT_FOUND = {
    "description": (
        "No such entity. Required, not optional: a 200 with an empty body is "
        "indistinguishable from a real record and produces confident wrong answers."
    ),
    "content": {"application/json": {"schema": {"$ref": REF_TEMPLATE.format(model="Error")}}},
}

_UNAUTHORISED = {
    "description": "Missing or invalid bearer token.",
    "content": {"application/json": {"schema": {"$ref": REF_TEMPLATE.format(model="Error")}}},
}

_ID_PARAM = {
    "name": "id",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "The store's own id, as a string. Ids are never integers on the wire.",
}

_PAGINATION_PARAMS = [
    {
        "name": "cursor",
        "in": "query",
        "schema": {"type": "string"},
        "description": "Opaque cursor from a previous page's next_cursor.",
    },
    {
        "name": "limit",
        "in": "query",
        "schema": {
            "type": "integer",
            "default": DEFAULT_PAGE_SIZE,
            "maximum": MAX_PAGE_SIZE,
            "minimum": 1,
        },
    },
    {
        "name": "updated_since",
        "in": "query",
        "schema": {"type": "string", "format": "date-time"},
        "description": (
            "ISO-8601, UTC. Only entities changed at or after this instant. Honour it "
            "or do not declare sync.incremental."
        ),
    },
    {
        "name": "locale",
        "in": "query",
        "schema": {"type": "string"},
        "description": "BCP-47. Ignore it if your store is single-locale.",
    },
]


def _paths() -> dict[str, Any]:
    return {
        PATH_HEALTH: {
            "get": {
                "operationId": "getHealth",
                "tags": ["connectivity"],
                "summary": "Reachability and declared capabilities",
                "description": (
                    "The only endpoint that may be served without a token, so a merchant "
                    "can verify their deployment before credentials exist."
                ),
                "security": [],
                "responses": {"200": _ok("Health")},
            }
        },
        PATH_PRODUCTS: {
            "get": {
                "operationId": "listProducts",
                "tags": ["catalogue"],
                "summary": "List or search products",
                "description": (
                    "With ?q= this is search (capability product.search); without it, the "
                    "bulk crawl used for catalogue sync (product.read). An empty result is "
                    "an empty page, never an error."
                ),
                "parameters": [
                    *_PAGINATION_PARAMS,
                    {"name": "q", "in": "query", "schema": {"type": "string"}},
                    {
                        "name": "category_ids",
                        "in": "query",
                        "schema": {"type": "string"},
                        "description": "Comma-separated category ids.",
                    },
                    {"name": "in_stock_only", "in": "query", "schema": {"type": "boolean"}},
                ],
                "responses": {"200": _ok("ProductPage"), "401": _UNAUTHORISED},
            }
        },
        PATH_PRODUCT: {
            "get": {
                "operationId": "getProduct",
                "tags": ["catalogue"],
                "parameters": [_ID_PARAM],
                "responses": {
                    "200": _ok("Product"),
                    "401": _UNAUTHORISED,
                    "404": _NOT_FOUND,
                },
            }
        },
        PATH_CATEGORIES: {
            "get": {
                "operationId": "listCategories",
                "tags": ["catalogue"],
                "summary": "The full category tree",
                "responses": {"200": _ok_array("Category"), "401": _UNAUTHORISED},
            }
        },
        PATH_INVENTORY: {
            "get": {
                "operationId": "getInventory",
                "tags": ["catalogue"],
                "parameters": [
                    {
                        "name": "variant_ids",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": (
                            "Comma-separated variant ids. Unknown ids are omitted from the "
                            "response rather than erroring."
                        ),
                    }
                ],
                "responses": {"200": _ok_array("InventoryLevel"), "401": _UNAUTHORISED},
            }
        },
        PATH_ORDERS: {
            "get": {
                "operationId": "listOrders",
                "tags": ["orders"],
                "summary": "List, sync or look up orders",
                "description": (
                    "Filtered by email, phone, customer_id or order_number this answers "
                    "'where is my order' (capability order.search); unfiltered it is the "
                    "sync crawl (order.read).\n\n"
                    "This endpoint returns whatever matches the filter. It is **not** an "
                    "authorisation boundary — verifying that the person asking owns the "
                    "order happens on our side, before the question is ever asked."
                ),
                "parameters": [
                    *_PAGINATION_PARAMS,
                    {"name": "email", "in": "query", "schema": {"type": "string"}},
                    {"name": "phone", "in": "query", "schema": {"type": "string"}},
                    {"name": "customer_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "order_number", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {"200": _ok("OrderPage"), "401": _UNAUTHORISED},
            }
        },
        PATH_ORDER: {
            "get": {
                "operationId": "getOrder",
                "tags": ["orders"],
                "parameters": [_ID_PARAM],
                "responses": {
                    "200": _ok("Order"),
                    "401": _UNAUTHORISED,
                    "404": _NOT_FOUND,
                },
            }
        },
        PATH_CUSTOMER: {
            "get": {
                "operationId": "getCustomer",
                "tags": ["customers"],
                "parameters": [_ID_PARAM],
                "responses": {
                    "200": _ok("Customer"),
                    "401": _UNAUTHORISED,
                    "404": _NOT_FOUND,
                },
            }
        },
        PATH_POLICIES: {
            "get": {
                "operationId": "listPolicies",
                "tags": ["content"],
                "summary": "Returns, shipping and warranty text",
                "description": (
                    "The text the agent grounds answers in. Without it, every returns "
                    "question becomes an escalation to a human."
                ),
                "responses": {"200": _ok_array("Policy"), "401": _UNAUTHORISED},
            }
        },
    }


def _webhooks() -> dict[str, Any]:
    return {
        "entityChanged": {
            "post": {
                "operationId": "entityChanged",
                "summary": "Tell us something changed (capability events.realtime)",
                "description": (
                    # G66 (ADR-0053 §5): described for later, received by nothing yet.
                    "Not used yet: NEURA has no address that receives these. Do not build "
                    "them; leave `events.realtime` out of `/health`.\n\n"
                    "Send the notification, not the data — we fetch the entity ourselves. "
                    "A notification carrying no customer data cannot leak one if it is "
                    "mis-delivered, and we always read the current state rather than a "
                    "payload that may have arrived out of order.\n\n"
                    f"Sign `<timestamp>.<raw body>` with HMAC-SHA256 and the shared secret. "
                    f"Send the hex digest as `{SIGNATURE_HEADER}: sha256=<digest>` and the "
                    f"same unix timestamp as `{TIMESTAMP_HEADER}`. Requests older than five "
                    "minutes are rejected, so an intercepted request cannot be replayed "
                    "indefinitely.\n\n"
                    "Deliver at least once and expect us to be idempotent; duplicates are "
                    "safe, silence is not."
                ),
                "parameters": [
                    {
                        "name": SIGNATURE_HEADER,
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "pattern": "^sha256=[0-9a-f]{64}$"},
                    },
                    {
                        "name": TIMESTAMP_HEADER,
                        "in": "header",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": REF_TEMPLATE.format(model="WebhookEvent")},
                            "examples": {
                                name.replace(".", "_"): {
                                    "value": {
                                        "event": name,
                                        "external_id": "1001",
                                        "occurred_at": "2026-07-26T10:00:00Z",
                                    }
                                }
                                for name in sorted(KNOWN_EVENTS)
                            },
                        }
                    },
                },
                "responses": {
                    "202": {"description": "Accepted. Retry on any other status."},
                    "401": {"description": "Signature missing, wrong, or too old."},
                },
            }
        }
    }


def render() -> str:
    """The document as it is committed. Stable ordering, so diffs are readable."""
    return json.dumps(build_openapi(), indent=2, ensure_ascii=False) + "\n"
