"""Conformance checks that only exist at the HTTP level.

The shared adapter suite in ``neura_commerce.conformance`` checks *behaviour*:
absent entities, empty searches, pagination that terminates. It runs against any
adapter, so by design it cannot see status codes, headers or authentication —
the adapter has already absorbed those.

Those are exactly where a Tier 2 implementation goes wrong, and one of them is
not a bug but an incident:

> **An unauthenticated ``/orders`` endpoint publishes a merchant's customer list
> to anyone who guesses the URL.** No agent behaviour is involved. If this tool
> reports nothing else, it must report that.

So these checks are additive, not a replacement — the CLI runs both and merges
the findings into one report.

**Orders are checked only in a shop that lists them** (G50). The guide lets a
shop start with its products alone, and many frameworks answer 404 for an
address that was never built, before any token check runs. Knocking on
``/orders`` there read that 404 as an open door: two false failures, and the
owner could not connect. So the token and not-found checks use orders when the
shop lists them and its products when it does not, and the order vocabulary
check runs only when there are orders to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from neura_adapters.generic.adapter import (
    PATH_HEALTH,
    PATH_ORDER,
    PATH_ORDERS,
    PATH_PRODUCT,
    PATH_PRODUCTS,
)
from neura_adapters.generic.client import GenericClient
from neura_adapters.generic.wire import SPEC_VERSION, spec_major
from neura_commerce import ConformanceReport, Severity
from neura_domain import Capability, FulfillmentStatus, OrderStatus, PaymentStatus, ProductStatus

_MISSING_ID = "__neura_conformance_missing__"

_REJECTING_STATUSES = (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN)

_STATUS_FIELDS = {
    "status": OrderStatus,
    "payment_status": PaymentStatus,
    "fulfillment_status": FulfillmentStatus,
}


@dataclass(frozen=True, slots=True)
class _Guarded:
    """Where the token and not-found checks knock (G50)."""

    collection: str
    one: str
    holds: str
    """What anyone could read if it were open, for the hint."""
    record: str
    a_record: str


#: Orders first: they hold customers' names and addresses, so an open /orders
#: is the incident this module exists to catch.
_ORDERS = _Guarded(PATH_ORDERS, PATH_ORDER, "orders", "order", "an order")
#: Every shop the check can pass reads products: the guide's first three addresses.
_PRODUCTS = _Guarded(PATH_PRODUCTS, PATH_PRODUCT, "products", "product", "a product")

_ORDER_CAPABILITIES = frozenset({Capability.ORDER_READ, Capability.ORDER_SEARCH})


def _guarded(capabilities: frozenset[Capability] | None) -> _Guarded:
    """The most sensitive address the shop says it has. ``None``: the strictest."""
    if capabilities is None or capabilities & _ORDER_CAPABILITIES:
        return _ORDERS
    return _PRODUCTS


async def run_http_checks(
    client: GenericClient,
    report: ConformanceReport,
    capabilities: frozenset[Capability] | None = None,
) -> None:
    """Append protocol-level findings to an existing report.

    ``capabilities`` is what the shop's ``/health`` listed; without it every
    address is checked, orders included.
    """
    guarded = _guarded(capabilities)
    await _check_auth(client, report, guarded)
    await _check_health_transport(client, report)
    await _check_not_found(client, report, guarded)
    await _check_limit(client, report)
    if guarded is _ORDERS:
        await _check_status_vocabulary(client, report)
    await _check_product_status_vocabulary(client, report)


async def _check_auth(client: GenericClient, report: ConformanceReport, guarded: _Guarded) -> None:
    check = "auth.required"

    if not client.has_token:
        report.add(
            check,
            Severity.WARNING,
            "no token supplied, so anonymous access could not be tested",
            "Re-run with --token. This is the check most worth passing: these "
            "endpoints expose customer and order data.",
        )
        return

    anonymous = await client.request(guarded.collection, authenticate=False)
    if anonymous.status_code not in _REJECTING_STATUSES:
        report.add(
            check,
            Severity.ERROR,
            f"{guarded.collection} answered an unauthenticated request "
            f"with HTTP {anonymous.status_code}",
            "Every endpoint except /health must return 401 without a valid bearer "
            f"token. As it stands, anyone who learns this URL can read the store's "
            f"{guarded.holds}.",
        )
    else:
        report.passed(check)

    check = "auth.rejects_wrong_token"
    wrong = await client.request(guarded.collection, token="not-a-real-token")  # noqa: S106
    if wrong.status_code not in _REJECTING_STATUSES:
        report.add(
            check,
            Severity.ERROR,
            f"{guarded.collection} accepted an invalid bearer token (HTTP {wrong.status_code})",
            "The token is being ignored rather than verified.",
        )
    else:
        report.passed(check)


async def _check_health_transport(client: GenericClient, report: ConformanceReport) -> None:
    check = "health.anonymous"
    response = await client.request(PATH_HEALTH, authenticate=False)
    if response.status_code in _REJECTING_STATUSES:
        report.add(
            check,
            Severity.WARNING,
            "/health requires a token",
            "Allowed, but /health without one lets a merchant verify their "
            "deployment before any credential has been issued.",
        )
    elif response.status_code != httpx.codes.OK:
        report.add(check, Severity.ERROR, f"/health returned HTTP {response.status_code}")
    else:
        report.passed(check)

    check = "health.content_type"
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        report.add(
            check,
            Severity.WARNING,
            f"/health content-type is {content_type or 'unset'!r}, expected application/json",
        )
    else:
        report.passed(check)

    check = "health.spec_version"
    payload = _json(response)
    declared = str(payload.get("spec_version", "")) if isinstance(payload, dict) else ""
    if not declared:
        report.add(
            check,
            Severity.ERROR,
            "/health does not declare spec_version",
            "Without it we cannot tell which version of the interface you implement, "
            "and a future revision becomes impossible to roll out safely.",
        )
    elif spec_major(declared) != spec_major(SPEC_VERSION):
        report.add(
            check,
            Severity.ERROR,
            f"store implements spec {declared}; this client speaks {SPEC_VERSION}",
            "Major versions are not compatible.",
        )
    else:
        report.passed(check)


async def _check_not_found(
    client: GenericClient, report: ConformanceReport, guarded: _Guarded
) -> None:
    check = "errors.not_found"
    response = await client.request(guarded.one.format(id=_MISSING_ID))

    if response.status_code == httpx.codes.NOT_FOUND:
        report.passed(check)
        return

    if response.status_code in _REJECTING_STATUSES:
        report.add(check, Severity.ERROR, "authentication failed — check the token")
        return

    report.add(
        check,
        Severity.ERROR,
        f"an unknown {guarded.record} id returned HTTP {response.status_code}, expected 404",
        "A 200 with an empty body is indistinguishable from a real record, and the "
        f"agent will answer a customer about {guarded.a_record} that does not exist.",
    )


async def _check_limit(client: GenericClient, report: ConformanceReport) -> None:
    check = "pagination.limit"
    response = await client.request(PATH_PRODUCTS, params={"limit": 2})
    payload = _json(response)

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        report.add(
            check,
            Severity.ERROR,
            f"{PATH_PRODUCTS} did not return an object with an 'items' array",
            'The collection envelope is {"items": [...], "next_cursor": "..."|null}.',
        )
        return

    if len(payload["items"]) > 2:
        report.add(
            check,
            Severity.WARNING,
            f"?limit=2 returned {len(payload['items'])} items",
            "Ignoring limit means one request can pull an entire catalogue into "
            "memory — on your server as much as ours.",
        )
        return

    report.passed(check)


async def _check_status_vocabulary(client: GenericClient, report: ConformanceReport) -> None:
    """Statuses in the raw JSON, before the client maps them.

    The adapter downgrades an unrecognised status to ``unknown`` so one bad value
    cannot make an order unreadable. That is the right runtime behaviour and the
    wrong thing to be silent about: "unknown" answers a customer's "where is my
    order?" with nothing.
    """
    check = "orders.status_vocabulary"
    response = await client.request(PATH_ORDERS, params={"limit": 5})
    if response.status_code != httpx.codes.OK:
        # Silent rather than green. A check that passes because the endpoint is
        # broken reads as reassurance, and another check is already reporting
        # the real failure.
        return

    payload = _json(response)
    items = payload.get("items", []) if isinstance(payload, dict) else []

    unmapped: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for field, enum_cls in _STATUS_FIELDS.items():
            value = item.get(field)
            if isinstance(value, str) and value not in {m.value for m in enum_cls}:
                unmapped.add(f"{field}={value!r}")

    if unmapped:
        report.add(
            check,
            Severity.WARNING,
            f"non-canonical status values: {sorted(unmapped)}",
            "Map your platform's vocabulary to the enums in the spec. Unrecognised "
            "values are read as 'unknown', which the agent cannot explain to a customer.",
        )
        return

    report.passed(check)


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


#: A sample, one request: enough to catch a bridge that maps statuses wrongly.
_PRODUCT_SAMPLE = 20

#: Read as "unknown" by the adapter, so never recommended.
_NO_STATUS = "no status"


async def _check_product_status_vocabulary(
    client: GenericClient, report: ConformanceReport
) -> None:
    """Statuses in the raw catalogue, before the client maps them.

    A missing status, ``"unknown"`` and any word the format does not know all
    end as ``unknown``, and NEURA-SELL, the suggestions and the product feed
    keep only ``active`` products (G69). The format allows a missing status, so
    this warns rather than fails: answering questions still works without it.
    ``draft`` and ``archived`` are not warned about: a shop hides those on purpose.
    """
    check = "products.status_vocabulary"
    response = await client.request(PATH_PRODUCTS, params={"limit": _PRODUCT_SAMPLE})
    if response.status_code != httpx.codes.OK:
        return

    payload = _json(response)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    products = [item for item in items if isinstance(item, dict)]

    usable = {member.value for member in ProductStatus} - {ProductStatus.UNKNOWN.value}
    unusable: dict[str, int] = {}
    for product in products:
        status = product.get("status")
        if isinstance(status, str) and status in usable:
            continue
        label = f'"{status}"' if isinstance(status, str) else _NO_STATUS
        unusable[label] = unusable.get(label, 0) + 1

    if unusable:
        named = ", ".join(
            f"{label} ({count})"
            for label, count in sorted(unusable.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        report.add(
            check,
            Severity.WARNING,
            f"{sum(unusable.values())} of {len(products)} products read have no usable status: "
            f"{named}",
            'Send "status": "active" for each product shoppers can buy now, and "draft" or '
            '"archived" for the rest. Any other word, or none, is read as "unknown", and '
            'NEURA-SELL never recommends a product that is not "active".',
        )
        return

    report.passed(check)
