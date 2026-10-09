"""What the developer MCP server teaches: the bridge's format, a sample for every
answer, and the rules developers get wrong (ADR-0053).

**It only teaches.** Nothing here calls a shop, reads a tenant or holds a secret,
and every word it returns is ours: there is no merchant text in it to carry an
injection, and nothing about any shop to leak. That is why the server built on
it may answer anyone, with no account and no token (ADR-0053 §3).

**It cannot teach something the code does not do**, because each part is tied to
the thing it describes, and ``tests/unit/test_developer_teacher.py`` fails when
the two part:

* **The formats** are cut from :func:`build_openapi`, the function that makes the
  published OpenAPI file. Nothing here restates a field.
* **Every sample** is read by the real :class:`GenericAdapter` over a fake shop
  that serves it, and has no field the OpenAPI file does not know (NEURA's
  reader would drop one quietly, so the reader alone cannot catch it).
* **The capability words** are the ones CARE's and SELL's tools require, and
  every other word in :class:`Capability` is named in a rule that says to leave
  it out.
* **The status words** are spelled from the enums, not typed.

**Platform-neutral on purpose**, like the rest of this package's published text:
the content goes to anyone, and Rule 1's names never appear in it (tested).

**The rules are the ones real bridges got wrong** on 2026-09-30 and after
(``docs/CONNECTING_A_NEW_SHOP_LOG.md``): staff sent as customers (G7), a draft
told to shoppers (G37), a status other than ``"ok"`` (G14), a missing product
status (G69), webhooks NEURA cannot receive (G66). One is not about the bridge:
the customer pass (ADR-0057), tied to the order addresses because a pass is
useless without them, built from ``check_customer_pass``'s own constants, and
carrying its security review's two rules as the developer guide does. The owner kept the long
"fit your data" list off the guide page, where a person reads every line (G4);
here an AI reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import cache
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
from neura_adapters.generic.spec import build_openapi
from neura_adapters.generic.wire import SPEC_VERSION
from neura_commerce import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neura_core.tenancy.customer_pass import (
    CUSTOMER_SECRET_PREFIX,
    MAX_PASS_LIFETIME,
    PASS_ALGORITHM,
)
from neura_domain import (
    Capability,
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    PolicyKind,
    ProductStatus,
)

#: The bridge format versions this teacher can teach. One today; when a 2.0
#: exists it is added here, and a developer whose shop is on 1.0 is never taught
#: 2.0 by surprise (ADR-0053 §4).
FORMAT_VERSIONS: tuple[str, ...] = (SPEC_VERSION,)


class TeacherError(ValueError):
    """A question the teacher has no answer for. The server turns it into an
    MCP error that names what it does know."""


class UnknownVersionError(TeacherError):
    pass


class UnknownAddressError(TeacherError):
    pass


class UnknownTopicError(TeacherError):
    pass


class Group(StrEnum):
    """The order to build in: the developer guide's three groups, step 1."""

    START = "start"
    BETTER = "better"
    ORDERS = "orders"


GROUPS: dict[Group, dict[str, str]] = {
    Group.START: {
        "title": "Start with these three",
        "note": "Enough to connect. The assistant can find products and talk about them.",
    },
    Group.BETTER: {
        "title": "Add these for better answers",
        "note": "Each one you add, the assistant can do one more thing.",
    },
    Group.ORDERS: {
        "title": "Only for order questions",
        "note": "For a shop that wants the assistant to look up orders.",
    },
}


@dataclass(frozen=True, slots=True)
class Rule:
    topic: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class Address:
    path: str
    answers: str
    group: Group
    #: The words to list in /health once this address works.
    capabilities: tuple[Capability, ...]
    sample_request: str
    sample: Any
    #: Topics of the rules that apply to this address.
    rules: tuple[str, ...]


# ── The samples ──────────────────────────────────────────────────────────────
#
# One small, consistent shop: one product in two sizes (the one step 1 of the
# developer guide shows, tested equal), its category, its stock, one customer
# and one order of it.


def _money(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "EUR"}


_ADDRESS = {
    "line1": "1 Example Street",
    "city": "Exampletown",
    "postcode": "12345",
    "country": "DE",
}

SAMPLE_PRODUCT: dict[str, Any] = {
    "external_id": "1042",
    "title": "Wool Hiking Socks",
    "description": "Warm merino socks for long walks.",
    "status": "active",
    "url": "https://yourshop.example/products/wool-hiking-socks",
    "image_urls": ["https://yourshop.example/images/wool-hiking-socks.jpg"],
    "category_ids": ["12"],
    "variants": [
        {
            "external_id": "1042-m",
            "title": "M",
            "options": {"size": "M"},
            "price": _money("12.00"),
            "in_stock": True,
            "stock_quantity": 8,
        },
        {
            "external_id": "1042-l",
            "title": "L",
            "options": {"size": "L"},
            "price": _money("12.00"),
            "in_stock": False,
            "stock_quantity": 0,
        },
    ],
}

SAMPLE_ORDER: dict[str, Any] = {
    "external_id": "5001",
    "order_number": "1001",
    "status": "shipped",
    "payment_status": "paid",
    "fulfillment_status": "fulfilled",
    "customer_external_id": "77",
    "customer_email": "ana@example.com",
    "lines": [
        {
            "external_id": "5001-1",
            "product_external_id": "1042",
            "variant_external_id": "1042-m",
            "title": "Wool Hiking Socks, M",
            "sku": "WHS-M",
            "quantity": 2,
            "unit_price": _money("12.00"),
            "total": _money("24.00"),
        }
    ],
    "fulfillments": [
        {
            "external_id": "5001-f1",
            "status": "fulfilled",
            "carrier": "Example Post",
            "tracking_number": "EX123456789",
            "tracking_url": "https://tracking.example/EX123456789",
            "shipped_at": "2026-09-28T14:05:00Z",
        }
    ],
    "subtotal": _money("24.00"),
    "shipping_total": _money("4.50"),
    "tax_total": _money("0.00"),
    "total": _money("28.50"),
    "shipping_address": _ADDRESS,
    "placed_at": "2026-09-27T10:12:00Z",
    "updated_at": "2026-09-28T14:05:00Z",
}

SAMPLE_HEALTH: dict[str, Any] = {
    "status": "ok",
    "spec_version": SPEC_VERSION,
    "platform": "yourshop",
    "capabilities": [
        Capability.PRODUCT_READ.value,
        Capability.PRODUCT_SEARCH.value,
        Capability.INVENTORY_READ.value,
        Capability.POLICY_READ.value,
        Capability.CATEGORY_READ.value,
        Capability.ORDER_READ.value,
        Capability.ORDER_SEARCH.value,
        Capability.CUSTOMER_READ.value,
    ],
}

SAMPLE_CATEGORIES: list[dict[str, Any]] = [
    {
        "external_id": "3",
        "name": "Clothing",
        "description": "Everything to wear outdoors.",
        "url": "https://yourshop.example/clothing",
    },
    {
        "external_id": "12",
        "name": "Socks",
        "parent_external_id": "3",
        "url": "https://yourshop.example/clothing/socks",
    },
]

SAMPLE_STOCK: list[dict[str, Any]] = [
    {"variant_external_id": "1042-m", "quantity": 8, "in_stock": True},
    {"variant_external_id": "1042-l", "quantity": 0, "in_stock": False},
]

SAMPLE_CUSTOMER: dict[str, Any] = {
    "external_id": "77",
    "email": "ana@example.com",
    "phone": "+15555550100",
    "first_name": "Ana",
    "last_name": "Example",
    "default_address": _ADDRESS,
    "order_count": 3,
    "total_spent": _money("86.50"),
    "created_at": "2025-11-02T09:00:00Z",
}

SAMPLE_POLICIES: list[dict[str, Any]] = [
    {
        "external_id": "returns",
        "kind": "returns",
        "title": "Returns",
        "body": "You can return unworn items within 30 days of delivery for a full refund.",
        "url": "https://yourshop.example/returns",
        "updated_at": "2026-09-01T00:00:00Z",
    },
    {
        "external_id": "delivery",
        "kind": "shipping",
        "title": "Delivery",
        "body": "We send orders within 2 working days. Delivery is free over 50.00 EUR.",
        "url": "https://yourshop.example/delivery",
        "updated_at": "2026-09-01T00:00:00Z",
    },
]


# ── The rules ────────────────────────────────────────────────────────────────


def _words(vocabulary: type[StrEnum]) -> str:
    return ", ".join(f'"{member.value}"' for member in vocabulary)


#: Capability words that belong to no address: optional, or not used.
EXTRA_CAPABILITIES: tuple[Capability, ...] = (Capability.INCREMENTAL_SYNC,)

#: Capability words a bridge should leave out of /health today.
LEAVE_OUT: tuple[Capability, ...] = (
    Capability.REALTIME_EVENTS,
    Capability.CART_READ,
    Capability.CART_WRITE,
    Capability.ORDER_WRITE,
)

RULES: tuple[Rule, ...] = (
    Rule(
        "token",
        "Check the shop token on every address except /health",
        "NEURA sends `Authorization: Bearer <shop token>`. Refuse a request without it, or with "
        "another token, with 401 or 403. Read the token from a setting, for example "
        "NEURA_SHOP_TOKEN, never from code. While you build, put any text in that setting; the "
        "shop owner makes the real token in their NEURA dashboard and sends it to you.",
    ),
    Rule(
        "read-only",
        "Every address only reads",
        "All nine addresses are GET. Nothing NEURA sends changes anything in the shop: no orders, "
        "no prices, no stock.",
    ),
    Rule(
        "health",
        "/health: the exact values, and only what you built",
        '/health answers without a token. "status" must be exactly "ok": anything else and NEURA '
        f'treats the shop as down. "spec_version" is "{SPEC_VERSION}". "platform" is your shop\'s '
        'own name, for information only. "capabilities" lists the words for what you built. List a '
        "word only once its address works: a word listed but not built fails quietly, because NEURA "
        'reads a 404 as "nothing there". A change to the list counts within a minute.',
    ),
    Rule(
        "paging",
        "Lists come a page at a time, by cursor",
        'Return "items" and "next_cursor": an opaque text NEURA sends back unchanged as ?cursor=, '
        "and null on the last page. Never page numbers or offsets. A cursor must move forward: one "
        "that repeats makes NEURA read for ever. Honour ?limit= (default "
        f"{DEFAULT_PAGE_SIZE}, at most {MAX_PAGE_SIZE}).",
    ),
    Rule(
        "not-found",
        "Something that does not exist answers 404",
        "A product, order or customer id that does not exist answers 404. Never a 200 with an "
        "empty body: NEURA would read it as a real record.",
    ),
    Rule(
        "products",
        "Products: status, variants, stock",
        f'"status" is one of {_words(ProductStatus)}. "active" means shoppers can buy it now; '
        'without "active" (a missing status is read as "unknown"), the assistant never '
        'recommends or suggests the product. "draft" is a product not released yet: NEURA never '
        'mentions it to a shopper. "archived" is a product no longer sold. Each size or colour is '
        'a variant, with its own "external_id", "price" and stock. A product with neither still '
        'needs one variant: that is where its price and stock go. "in_stock" is true only if the '
        'variant can be bought now; send "stock_quantity" too if the shop counts stock.',
    ),
    Rule(
        "money",
        "Prices: text and a three-letter currency",
        '"amount" is text, a decimal number such as "12.00", with no currency sign. "currency" is '
        'the three capital letters of ISO 4217, such as "EUR" or "USD", never a sign such as "€". '
        '"price" is what a shopper pays today: the sale price, if there is one.',
    ),
    Rule(
        "search",
        "Search: the words shoppers type",
        "/products?q= is the search. Match the shopper's words against product titles and "
        "descriptions. Filters you cannot apply (category_ids, in_stock_only) may be ignored: no "
        "assistant sends them today.",
    ),
    Rule(
        "orders",
        "Orders: map the shop's own words",
        '"order_number" is the number the customer sees on their receipt. "status" is one of '
        f'{_words(OrderStatus)}. "payment_status" is one of {_words(PaymentStatus)}. '
        f'"fulfillment_status" is one of {_words(FulfillmentStatus)}. Map the shop\'s own words to '
        'the nearest: anything else is read as "unknown", which the assistant cannot explain to a '
        'customer. Tracking goes in "fulfillments". /orders searches by ?email=, ?phone=, '
        "?customer_id= or ?order_number= and returns only the orders that match. A country is the "
        'two-letter ISO 3166 code, such as "DE".',
    ),
    Rule(
        "customers",
        "Customers only, never staff",
        "/customers/{id} answers one customer of the shop. Never a member of staff or an admin: an "
        "id that belongs to staff answers 404, like an id that does not exist.",
    ),
    Rule(
        "policies",
        "Policy pages",
        f'Each policy has a "kind": one of {_words(PolicyKind)}. "body" is the page\'s text. A shop '
        f'with no such pages leaves "{Capability.POLICY_READ.value}" out of /health: the assistant '
        "then cannot answer returns or delivery questions.",
    ),
    Rule(
        "categories",
        "Categories",
        '"parent_external_id" links a category to the one above it. The assistant names the '
        "shop's categories when nothing fits what a shopper asked for.",
    ),
    Rule(
        "incremental",
        "Only what changed: optional",
        f'List "{Capability.INCREMENTAL_SYNC.value}" only if /products and /orders both honour '
        "?updated_since= (ISO 8601, UTC) and return only what changed at or after it. Listing it "
        "and ignoring it is worse than leaving it out: without it, NEURA reads every product each "
        "time.",
    ),
    Rule(
        "webhooks",
        "Do not build webhooks to NEURA yet",
        "The OpenAPI file describes them (entityChanged), but NEURA has no address that receives "
        f'them. Leave "{Capability.REALTIME_EVENTS.value}" out of /health. Nothing is lost: the '
        "assistant asks your bridge live, so it sees a new product or a stock change straight away.",
    ),
    Rule(
        "not-used",
        "Words NEURA does not use",
        f'"{Capability.CART_READ.value}", "{Capability.CART_WRITE.value}" and '
        f'"{Capability.ORDER_WRITE.value}": NEURA only reads, and no assistant uses them. Leave them '
        "out of /health.",
    ),
    Rule(
        "address",
        "A public https address, with no redirect",
        "In production NEURA calls only a public https:// address, never localhost or a private "
        "network, and does not follow redirects. Send the shop owner the exact address /health "
        "sits under: the address that passes the check is the one that gets connected.",
    ),
    Rule(
        "check",
        "How the bridge is checked",
        "There is no check tool to download. The shop owner presses Check in their NEURA "
        "dashboard and sends you the full result. When one cause explains every failure, the first "
        "line names it.",
    ),
    Rule(
        "customer-pass",
        "Order questions from signed-in shoppers: the customer pass",
        "Optional, and built in the shop's pages, not the bridge. Without it, every order question "
        "in the chat box is answered with a fixed sentence: sign in, or contact the shop. The shop "
        f"owner makes the customer sign-in secret ({CUSTOMER_SECRET_PREFIX}…) on Shop connection in "
        "their NEURA dashboard and sends it to you. Keep it in a server setting, for example "
        "NEURA_CUSTOMER_SECRET, never in a web page. Each time the shop's server draws a page for "
        "a signed-in customer, it makes a fresh pass: a JSON Web Token signed with "
        f"{PASS_ALGORITHM}, using the whole secret, {CUSTOMER_SECRET_PREFIX} included, as the key. "
        'It carries exactly three claims: "sub", the customer\'s id as text ("385", not 385: a '
        'number is refused), the same id the bridge sends as "customer_external_id" on that '
        "customer's orders (NEURA asks /orders?customer_id= with it, and keeps only the orders "
        'whose customer_external_id matches); "iat"; and "exp", at most '
        f"{int(MAX_PASS_LIFETIME.total_seconds() // 60)} minutes after iat. Any other claim, or "
        f"any algorithm but {PASS_ALGORITHM}, is refused. Write it into the chat box line as "
        "data-neura-customer-pass, only for a signed-in customer. Optional: "
        "data-neura-sign-in-url, the sign-in page as a full https:// address, adds a Sign in link "
        "for a shopper who is not signed in. Two rules NEURA cannot check for you: take the "
        "customer's id only from the shop's own sign-in session, never from anything in the "
        "request, and never build an address that makes a pass on request; and send a page that "
        "carries a pass with Cache-Control: private, no-store, kept out of any page cache. Each "
        'chat reply says "customer_pass": "valid", "expired" or "invalid", with '
        '"customer_pass_reason"; the browser console warns once per page when it is invalid. The '
        "developer guide's Optional: order questions shows samples in PHP and Node.js.",
    ),
)

_RULES_BY_TOPIC = {rule.topic: rule for rule in RULES}


# ── The addresses ────────────────────────────────────────────────────────────

ADDRESSES: tuple[Address, ...] = (
    Address(
        PATH_HEALTH,
        "What your shop can do: the list NEURA reads first. No token.",
        Group.START,
        (),
        "/health",
        SAMPLE_HEALTH,
        ("health", "webhooks", "not-used", "incremental"),
    ),
    Address(
        PATH_PRODUCTS,
        "A page of products; with ?q=, a search.",
        Group.START,
        (Capability.PRODUCT_READ, Capability.PRODUCT_SEARCH),
        "/products?q=wool+socks&limit=20",
        {"items": [SAMPLE_PRODUCT], "next_cursor": None},
        ("token", "paging", "search", "products", "money"),
    ),
    Address(
        PATH_PRODUCT,
        "One product, with its variants.",
        Group.START,
        (Capability.PRODUCT_READ,),
        "/products/1042",
        SAMPLE_PRODUCT,
        ("token", "not-found", "products", "money"),
    ),
    Address(
        PATH_INVENTORY,
        "Stock: whether each variant can be bought now.",
        Group.BETTER,
        (Capability.INVENTORY_READ,),
        "/inventory?variant_ids=1042-m,1042-l",
        SAMPLE_STOCK,
        ("token", "products"),
    ),
    Address(
        PATH_POLICIES,
        "Returns, delivery and other policy pages.",
        Group.BETTER,
        (Capability.POLICY_READ,),
        "/policies",
        SAMPLE_POLICIES,
        ("token", "policies"),
    ),
    Address(
        PATH_CATEGORIES,
        "The shop's categories.",
        Group.BETTER,
        (Capability.CATEGORY_READ,),
        "/categories",
        SAMPLE_CATEGORIES,
        ("token", "categories"),
    ),
    Address(
        PATH_ORDERS,
        "A page of orders: a search by email, phone, customer id or order number.",
        Group.ORDERS,
        (Capability.ORDER_SEARCH,),
        "/orders?email=ana@example.com",
        {"items": [SAMPLE_ORDER], "next_cursor": None},
        ("token", "paging", "orders", "money", "customer-pass"),
    ),
    Address(
        PATH_ORDER,
        "One order, with its lines and tracking.",
        Group.ORDERS,
        (Capability.ORDER_READ,),
        "/orders/5001",
        SAMPLE_ORDER,
        ("token", "not-found", "orders", "money", "customer-pass"),
    ),
    Address(
        PATH_CUSTOMER,
        "One customer of the shop, never a member of staff.",
        Group.ORDERS,
        (Capability.CUSTOMER_READ,),
        "/customers/77",
        SAMPLE_CUSTOMER,
        ("token", "not-found", "customers", "customer-pass"),
    ),
)

_ADDRESSES_BY_PATH = {address.path: address for address in ADDRESSES}


# ── The four answers (the MCP server's four tools, ADR-0053 §4) ──────────────


def _checked(version: str | None) -> str:
    chosen = version or SPEC_VERSION
    if chosen not in FORMAT_VERSIONS:
        raise UnknownVersionError(
            f"Format version {chosen!r} is not taught. Taught: {', '.join(FORMAT_VERSIONS)}."
        )
    return chosen


def _rule(rule: Rule) -> dict[str, str]:
    return {"topic": rule.topic, "title": rule.title, "text": rule.text}


def list_addresses(version: str | None = None) -> dict[str, Any]:
    """The nine addresses, in the order to build them."""
    return {
        "format_version": _checked(version),
        "how_to_start": "Build the first three, connect, and add the rest later.",
        "groups": [
            {
                "group": group.value,
                **GROUPS[group],
                "addresses": [
                    {
                        "path": address.path,
                        "answers": address.answers,
                        "capabilities": [c.value for c in address.capabilities],
                        "sample_request": address.sample_request,
                    }
                    for address in ADDRESSES
                    if address.group is group
                ],
            }
            for group in Group
        ],
        "optional_capabilities": [c.value for c in EXTRA_CAPABILITIES],
        "leave_out": [c.value for c in LEAVE_OUT],
    }


def get_address(path: str, version: str | None = None) -> dict[str, Any]:
    """One address: its request, its answer's format, a sample, and its rules."""
    chosen = _checked(version)
    address = _ADDRESSES_BY_PATH.get(path)
    if address is None:
        raise UnknownAddressError(
            f"No address {path!r}. The nine: {', '.join(a.path for a in ADDRESSES)}."
        )
    request = _document()["paths"][path]["get"]
    return {
        "format_version": chosen,
        "path": address.path,
        "answers": address.answers,
        "group": address.group.value,
        "capabilities": [c.value for c in address.capabilities],
        "request": request,
        "schemas": _schemas_for(request),
        "sample_request": address.sample_request,
        "sample_answer": address.sample,
        "rules": [_rule(_RULES_BY_TOPIC[topic]) for topic in address.rules],
    }


def get_rules(topic: str | None = None, version: str | None = None) -> dict[str, Any]:
    """Every rule, or the one for a topic."""
    chosen = _checked(version)
    if topic is None:
        return {"format_version": chosen, "rules": [_rule(rule) for rule in RULES]}
    rule = _RULES_BY_TOPIC.get(topic)
    if rule is None:
        raise UnknownTopicError(f"No topic {topic!r}. Topics: {', '.join(_RULES_BY_TOPIC)}.")
    return {"format_version": chosen, "rules": [_rule(rule)]}


def get_openapi(version: str | None = None) -> dict[str, Any]:
    """The whole OpenAPI file, for a code generator."""
    return {"format_version": _checked(version), "openapi": _document()}


@cache
def _document() -> dict[str, Any]:
    """Built once: the format does not change while the process runs."""
    return build_openapi()


def _schemas_for(node: Any) -> dict[str, Any]:
    """Every component schema ``node`` refers to, directly or through another."""
    components = _document()["components"]["schemas"]
    found: dict[str, Any] = {}
    waiting = _refs(node)
    while waiting:
        name = waiting.pop()
        if name in found:
            continue
        found[name] = components[name]
        waiting.extend(_refs(components[name]))
    return dict(sorted(found.items()))


def _refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        names: list[str] = []
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                names.append(value.rsplit("/", 1)[-1])
            else:
                names.extend(_refs(value))
        return names
    if isinstance(node, list):
        return [name for item in node for name in _refs(item)]
    return []


__all__ = [
    "ADDRESSES",
    "EXTRA_CAPABILITIES",
    "FORMAT_VERSIONS",
    "LEAVE_OUT",
    "RULES",
    "Address",
    "Group",
    "Rule",
    "TeacherError",
    "UnknownAddressError",
    "UnknownTopicError",
    "UnknownVersionError",
    "get_address",
    "get_openapi",
    "get_rules",
    "list_addresses",
]
