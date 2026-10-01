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
        report.add(check, Severity.ERROR, f"health() raised: {exc}", "health() must never raise")
        return

    if not status.ok:
        report.add(check, Severity.ERROR, f"store reports unhealthy: {status.detail}")
        return

    if not status.capabilities:
        report.add(
            check,
            Severity.ERROR,
            "no capabilities declared",
            "A store declaring nothing is reachable but unusable — the agent gets no tools.",
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
            f"get_product() raised for a missing id: {type(exc).__name__}",
            "Return None. Customers mistype ids constantly; that is not an error.",
        )
        return

    if result is not None:
        report.add(check, Severity.ERROR, "get_product() returned data for a nonexistent id")
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
            f"search_products() raised on an empty query: {type(exc).__name__}",
            "Return an empty page. A search matching nothing is the commonest case.",
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
                "search returned results for nonsense text",
                "Over-broad matching floods the agent's context with irrelevant products.",
            )
        else:
            report.passed(check)
    except Exception as exc:
        report.add(check, Severity.ERROR, f"search_products() raised: {type(exc).__name__}")

    check = "products.canonical_status"
    try:
        page = await adapter.search_products(ProductQuery(limit=5))
        for product in page.items:
            if product.status not in set(ProductStatus):
                report.add(
                    check,
                    Severity.ERROR,
                    f"product {product.external_id} has non-canonical status {product.status!r}",
                    "Map platform statuses to ProductStatus; unmappable values become UNKNOWN.",
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
            f"get_order() raised for a missing id: {type(exc).__name__}",
            "Return None.",
        )
        return

    if result is not None:
        report.add(check, Severity.ERROR, "get_order() returned data for a nonexistent id")
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
                    f"order {order.external_id} has non-canonical status {order.status!r}",
                    "A platform status string must never reach the agent.",
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
        report.add(check, Severity.ERROR, f"get_customer() raised: {type(exc).__name__}")
        return

    if result is not None:
        report.add(check, Severity.ERROR, "get_customer() returned data for a nonexistent id")
        return

    report.passed(check)


async def _check_policies(adapter: CommerceAdapter, report: ConformanceReport) -> None:
    check = "policies"
    try:
        policies = await adapter.get_policies()
    except Exception as exc:
        report.add(check, Severity.ERROR, f"get_policies() raised: {type(exc).__name__}")
        return

    if not policies:
        report.add(
            check,
            Severity.WARNING,
            "no policies returned",
            "Returns and shipping questions are a third of support volume. "
            "Without policy text the agent can only escalate them.",
        )
        return

    empty = [p.external_id for p in policies if not p.body.strip()]
    if empty:
        report.add(check, Severity.WARNING, f"policies with empty body: {empty}")
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
        report.add(check, Severity.ERROR, f"list_products() raised with updated_since: {exc}")
        return

    if page.items:
        report.add(
            check,
            Severity.WARNING,
            "declares sync.incremental but ignores updated_since "
            "(returned items updated after 2099)",
            "Either honour the filter or drop the capability — we will full-sync instead.",
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
                    "Use a stable sort plus a cursor, never LIMIT/OFFSET.",
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
                    "next_cursor did not advance — sync would loop forever",
                )
                return
            cursor = page.next_cursor
        report.passed(check)
    except Exception as exc:
        report.add(check, Severity.ERROR, f"pagination raised: {type(exc).__name__}: {exc}")
