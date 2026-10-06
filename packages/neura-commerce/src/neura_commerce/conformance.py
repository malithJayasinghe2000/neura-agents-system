"""The shared conformance suite every adapter must pass.

An interface is only real if something checks it. This suite is that check: it
runs identically against any adapter, so "works with any platform" is verified
rather than asserted.

It deliberately tests the **awkward** paths, because those are where adapters
actually diverge and where a plausible-looking implementation quietly breaks the
agent:

* absent entities return ``None``, they do not raise;
* an empty search returns an empty page, it does not error;
* declared capabilities match the methods that actually work;
* pagination terminates and does not repeat items;
* platform status vocabulary never leaks into a canonical model.

Usable both as a library (the conformance CLI in milestone 1.6) and directly
from pytest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from neura_commerce.pagination import Cursor
from neura_commerce.protocol import CommerceAdapter
from neura_commerce.queries import ProductQuery, SyncQuery
from neura_domain import Capability, OrderStatus, ProductStatus


class Severity(StrEnum):
    ERROR = "error"
    """Not conformant. The agent will misbehave."""

    WARNING = "warning"
    """Conformant but inconsistent — usually a capability declared and not honoured."""

    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    severity: Severity
    message: str
    hint: str = ""


@dataclass(slots=True)
class ConformanceReport:
    platform: str
    findings: list[Finding] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def is_conformant(self) -> bool:
        return not self.errors

    def add(self, check: str, severity: Severity, message: str, hint: str = "") -> None:
        self.findings.append(Finding(check, severity, message, hint))

    def passed(self, check: str) -> None:
        self.passed_checks.append(check)


@runtime_checkable
class ProtocolChecks(Protocol):
    """An adapter that can check what the shared suite cannot see.

    The shared suite runs *through* the adapter, so status codes, headers and the
    token are already absorbed by the time it looks. An adapter that speaks a wire
    protocol of its own may check those as well. Found by its shape, never by an
    import: the core must not learn which adapters exist (ADR-0052 §4).
    """

    async def run_protocol_checks(self, report: ConformanceReport) -> None: ...


async def check_adapter(adapter: CommerceAdapter) -> ConformanceReport:
    """Every check there is for one adapter: the shared suite, then its own.

    The one implementation behind both the terminal tool and the dashboard's
    *Check* (ADR-0052 §4), so the two can never disagree about a shop.
    """
    report = await run_conformance(adapter)
    if isinstance(adapter, ProtocolChecks):
        await adapter.run_protocol_checks(report)
    return report


async def run_conformance(adapter: CommerceAdapter) -> ConformanceReport:
    """Check one adapter against the contract."""
    report = ConformanceReport(platform=getattr(adapter, "platform", "unknown"))

    await _check_health(adapter, report)
    declared: frozenset[Capability] = getattr(adapter, "capabilities", frozenset())

    if Capability.PRODUCT_READ in declared:
        await _check_product_read(adapter, report)
    if Capability.PRODUCT_SEARCH in declared:
        await _check_product_search(adapter, report)
    if Capability.ORDER_READ in declared:
        await _check_order_read(adapter, report)
    if Capability.CUSTOMER_READ in declared:
        await _check_customer_read(adapter, report)
    if Capability.POLICY_READ in declared:
        await _check_policies(adapter, report)
    if Capability.INCREMENTAL_SYNC in declared:
        await _check_incremental_sync(adapter, report)

    await _check_pagination(adapter, report)
    return report


async def _check_health(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    check = "health"
    try:
        status = await adapter.health()
    except Exception as exc:
        report.add(
            check,
            Severity.ERROR,
            f"asking /health failed: {exc}",
            "GET /health must always answer, even when something else is wrong.",
        )
        return

    if not status.ok:
        report.add(check, Severity.ERROR, f"store reports unhealthy: {status.detail}")
        return

    if not status.capabilities:
        report.add(
            check,
            Severity.ERROR,
            "no capabilities declared",
            'With an empty "capabilities" list the assistant can do nothing with your shop. '
            "List each thing you built (step 2 of the guide).",
        )
        return

    declared: frozenset[Capability] = getattr(adapter, "capabilities", frozenset())
    if declared and status.capabilities != declared:
        only_runtime = status.capabilities - declared
        only_static = declared - status.capabilities
        report.add(
            check,
            Severity.WARNING,
            f"health() capabilities differ from the class attribute "
            f"(only in health: {sorted(c.value for c in only_runtime)}, "
            f"only on class: {sorted(c.value for c in only_static)})",
            "Tool filtering uses one of these. Disagreement means unpredictable behaviour.",
        )
        return

    report.passed(check)


async def _check_product_read(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    check = "products.get_missing"
    try:
        result = await adapter.get_product("__definitely_does_not_exist__")
    except Exception as exc:
        report.add(
            check,
            Severity.ERROR,
            f"asking for a product that does not exist failed: {type(exc).__name__}",
            "Answer 404 for a product id that does not exist. Shoppers mistype ids all the "
            "time; that is not an error.",
        )
        return

    if result is not None:
        report.add(
            check,
            Severity.ERROR,
            "a product that does not exist was answered with data",
            "Answer 404, not a product, for an id that does not exist.",
        )
        return

    report.passed(check)


async def _check_product_search(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    check = "products.search_empty"
    try:
        page = await adapter.search_products(ProductQuery(text=""))
    except Exception as exc:
        report.add(
            check,
            Severity.ERROR,
            f"a search that finds nothing failed: {type(exc).__name__}",
            'Answer an empty list: {"items": [], "next_cursor": null}. A search that finds '
            "nothing is the most common case.",
        )
        return

    report.passed(check)

    check = "products.search_no_match"
    try:
        page = await adapter.search_products(ProductQuery(text="zzzz_no_such_product_zzzz"))
        if page.items:
            report.add(
                check,
                Severity.WARNING,
                "a search for nonsense text found products",
                "Match the words a shopper typed. Matching everything gives the assistant "
                "products that have nothing to do with the question.",
            )
        else:
            report.passed(check)
    except Exception as exc:
        report.add(check, Severity.ERROR, f"a product search failed: {type(exc).__name__}")

    check = "products.canonical_status"
    try:
        page = await adapter.search_products(ProductQuery(limit=5))
        for product in page.items:
            if product.status not in set(ProductStatus):
                report.add(
                    check,
                    Severity.ERROR,
                    f"product {product.external_id} has a status NEURA does not know: "
                    f"{product.status!r}",
                    'Use "active", "draft" or "archived". Any other word is read as "unknown".',
                )
                return
        report.passed(check)
    except Exception:  # noqa: S110
        pass


async def _check_order_read(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    check = "orders.get_missing"
    try:
        result = await adapter.get_order("__definitely_does_not_exist__")
    except Exception as exc:
        report.add(
            check,
            Severity.ERROR,
            f"asking for an order that does not exist failed: {type(exc).__name__}",
            "Answer 404 for an order id that does not exist.",
        )
        return

    if result is not None:
        report.add(
            check,
            Severity.ERROR,
            "an order that does not exist was answered with data",
            "Answer 404, not an order, for an id that does not exist.",
        )
        return

    report.passed(check)

    check = "orders.canonical_status"
    try:
        page = await adapter.list_orders(SyncQuery(limit=5))
        for order in page.items:
            if order.status not in set(OrderStatus):
                report.add(
                    check,
                    Severity.ERROR,
                    f"order {order.external_id} has a status NEURA does not know: {order.status!r}",
                    "Use the order status words the OpenAPI file lists. Your shop's own words "
                    "would reach the assistant, which cannot explain them to a shopper.",
                )
                return
        report.passed(check)
    except Exception:  # noqa: S110
        pass


async def _check_customer_read(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    check = "customers.get_missing"
    try:
        result = await adapter.get_customer("__definitely_does_not_exist__")
    except Exception as exc:
        report.add(
            check,
            Severity.ERROR,
            f"asking for a customer that does not exist failed: {type(exc).__name__}",
            "Answer 404 for a customer id that does not exist.",
        )
        return

    if result is not None:
        report.add(
            check,
            Severity.ERROR,
            "a customer that does not exist was answered with data",
            "Answer 404, not a customer, for an id that does not exist.",
        )
        return

    report.passed(check)


async def _check_policies(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    check = "policies"
    try:
        policies = await adapter.get_policies()
    except Exception as exc:
        report.add(check, Severity.ERROR, f"reading the policy pages failed: {type(exc).__name__}")
        return

    if not policies:
        report.add(
            check,
            Severity.WARNING,
            "no policies returned",
            "Without policy text the assistant cannot answer returns or shipping questions. "
            "If the shop has no policy pages, leave policy.read out of the list.",
        )
        return

    empty = [p.external_id for p in policies if not p.body.strip()]
    if empty:
        report.add(
            check,
            Severity.WARNING,
            f"policy pages with no text: {empty}",
            "Send each page's text, or leave that page out.",
        )
        return

    report.passed(check)


async def _check_incremental_sync(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    """A store claiming INCREMENTAL_SYNC must honour ``updated_since``.

    Claiming it and ignoring it is worse than not claiming it: we would sync only
    recent changes and silently never notice the rest.
    """
    from datetime import UTC, datetime

    check = "sync.updated_since"
    try:
        future = datetime(2099, 1, 1, tzinfo=UTC)
        page = await adapter.list_products(SyncQuery(updated_since=future))
    except Exception as exc:
        report.add(check, Severity.ERROR, f"reading products changed since a date failed: {exc}")
        return

    if page.items:
        report.add(
            check,
            Severity.WARNING,
            "declares sync.incremental but ignores updated_since "
            "(returned items updated after 2099)",
            "Honour updated_since, or leave sync.incremental out of the list: NEURA then "
            "reads every product each time.",
        )
        return

    report.passed(check)


async def _check_pagination(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    """Pagination must terminate and must not repeat items.

    A cursor that never advances makes sync loop forever; one that repeats items
    inflates the catalogue with duplicates.
    """
    check = "pagination"
    seen: set[str] = set()
    cursor: Cursor | None = None

    try:
        for page_number in range(1, 6):
            page = await adapter.list_products(SyncQuery(limit=2), cursor)

            duplicates = {p.external_id for p in page.items} & seen
            if duplicates:
                report.add(
                    check,
                    Severity.ERROR,
                    f"page {page_number} repeated ids: {sorted(duplicates)}",
                    "Sort by something that never changes, such as the id, and continue from "
                    "the cursor. Page numbers with an offset repeat or skip products when the "
                    "catalogue changes.",
                )
                return
            seen.update(p.external_id for p in page.items)

            if not page.has_more:
                report.passed(check)
                return

            if page.next_cursor == cursor:
                report.add(
                    check,
                    Severity.ERROR,
                    "next_cursor did not move on, so reading the catalogue would never end",
                    "Send the cursor of the next page, or null on the last page.",
                )
                return
            cursor = page.next_cursor
        report.passed(check)
    except Exception as exc:
        report.add(
            check,
            Severity.ERROR,
            f"reading products page by page failed: {type(exc).__name__}: {exc}",
        )
