"""The ``shop.check`` handler: the full check, run by NEURA's own server. ADR-0052 §4.

The dashboard's *Check* queues this job; the page then asks our own server every
few seconds whether the result is ready, as *Sync now* does. **It runs in the
background, never inside the page's request**: the check asks the shop about
twenty questions and each may wait up to ten seconds, so a slow shop would
otherwise hold one of our servers for minutes. Running it here adds no calls to
the shop.

**It is the check tool, not a copy of it.** ``neura_commerce.check_adapter`` runs
the shared suite and then whatever wire checks the adapter offers, exactly as
``neura-conformance`` does, so the terminal and the dashboard can never disagree
about a shop. The adapter is built through the registry, never imported (the
API may not learn that an adapter package exists).

**One cause first** (G48). One wrong token used to show as eight failures, most
with the wrong advice. Before the suite runs, two plain requests ask the only
questions that make everything else irrelevant: can we reach a bridge at all, and
does it accept the token? The answer is written as ``cause``; the screen says
that one thing, and the developer still gets the full list.

**A check that finds problems has succeeded.** ``done`` with findings is the
normal result; ``failed`` means we could not run it, and the job is never retried
(``max_attempts=1``): asking a broken shop the same twenty questions five times
helps nobody.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from neura_api.addresses import adapter_transport, check_shop_address
from neura_api.jobs.runner import JobContext
from neura_commerce import (
    AdapterAuthError,
    AdapterError,
    AdapterTimeoutError,
    AdapterUnavailableError,
    ConformanceReport,
    ProductQuery,
    Severity,
    check_adapter,
    registry,
)
from neura_core import ValidationError, get_logger
from neura_core.jobs import JobQueue
from neura_core.tenancy import ShopCheckRepository, ShopTokenRepository, StoreConnectionRepository

log = get_logger(__name__)

SHOP_CHECK = "shop.check"

#: One check in flight per shop (ADR-0052 §4). A second press while one runs
#: gets the running one back, so the shop is never asked twice at once.
CHECK_DEDUPE_KEY = "check"

#: The interface a connection made in the dashboard speaks: the Standard NEURA
#: bridge. Data, not behaviour: the adapter is found by this name in the
#: registry, exactly as ``POST /v1/stores`` finds one.
STANDARD_BRIDGE = "generic"

#: The causes the screen turns into one sentence. ``None`` means none of them:
#: the findings speak for themselves.
UNREACHABLE = "unreachable"
NO_BRIDGE = "no_bridge"
NOT_OK = "not_ok"
# S105 reads these as passwords; they name causes, and no secret is near them.
TOKEN_REFUSED = "token_refused"  # noqa: S105
ADDRESS_REFUSED = "address_refused"
NO_TOKEN = "no_token"  # noqa: S105


async def enqueue_check(session: Any, tenant_id: str, check_id: str) -> Any:
    """Queue one check, inside the caller's transaction, never retried."""
    return await JobQueue(session).enqueue(
        tenant_id,
        SHOP_CHECK,
        payload={"check_id": check_id},
        max_attempts=1,
        dedupe_key=CHECK_DEDUPE_KEY,
    )


async def live_check_id(session: Any, tenant_id: str) -> str | None:
    """The check still queued or running for this shop, if any."""
    job = await JobQueue(session).find_by_dedupe(
        tenant_id, SHOP_CHECK, CHECK_DEDUPE_KEY, live_only=True
    )
    if job is None:
        return None
    check_id = job.payload.get("check_id")
    return str(check_id) if check_id else None


class ShopCheckHandler:
    """Runs one queued check and writes its result."""

    def __init__(self, *, production: bool) -> None:
        self._production = production

    async def __call__(self, context: JobContext) -> str:
        check_id = str(context.job.payload.get("check_id") or "")
        tenant_id = context.tenant_id

        async with context.db.tenant_session(tenant_id) as session:
            check = await ShopCheckRepository(session).get(tenant_id, check_id)
        if check is None:
            return f"check {check_id} no longer exists"

        failed = False
        try:
            result = await self._run_check(context, tenant_id, check)
        except Exception as exc:
            # Whatever went wrong, the check must end: a row left `pending` would
            # keep the owner's screen saying "Checking…" for ever. Logged loudly,
            # because unlike a shop's own problems, this one is ours.
            log.exception("shop_check_crashed", tenant_id=tenant_id, check_id=check_id)
            failed = True
            result = outcome(check["address"], cause=None, message=type(exc).__name__)

        async with context.db.tenant_session(tenant_id) as session:
            await ShopCheckRepository(session).finish(check_id, result=result, failed=failed)

        log.info(
            "shop_check_finished",
            tenant_id=tenant_id,
            check_id=check_id,
            cause=result["cause"],
            passed=result["passed"],
            failed=result["failed"],
        )
        return f"check {check_id}: {result['passed']} passed, {result['failed']} failed"

    async def _run_check(
        self, context: JobContext, tenant_id: str, check: dict[str, Any]
    ) -> dict[str, Any]:
        """The token and the platform, read on the server, then the check itself."""
        platform = STANDARD_BRIDGE
        async with context.db.tenant_session(tenant_id) as session:
            if check["store_id"] is None:
                credentials = await ShopTokenRepository(session).credentials(tenant_id)
            else:
                stores = StoreConnectionRepository(session)
                credentials = await stores.credentials_for(tenant_id, check["store_id"])
                platform = next(
                    (
                        row["platform"]
                        for row in await stores.list_for(tenant_id)
                        if row["id"] == check["store_id"]
                    ),
                    STANDARD_BRIDGE,
                )
        return await self._run(check["address"], platform, tenant_id, credentials)

    async def _run(
        self, address: str, platform: str, tenant_id: str, credentials: dict[str, str] | None
    ) -> dict[str, Any]:
        if not credentials:
            return outcome(address, cause=NO_TOKEN)
        try:
            address = await check_shop_address(address, production=self._production)
        except ValidationError as refused:
            return outcome(address, cause=ADDRESS_REFUSED, message=refused.message)

        adapter = registry.create(
            platform,
            base_url=address,
            tenant_id=tenant_id,
            # The address was just checked; the connection checks it again as it
            # connects, so a name that changes its answer in between is refused.
            **adapter_transport(production=self._production),
            **credentials,
        )
        try:
            cause, capabilities = await diagnose(adapter)
            report = None
            if cause in (None, TOKEN_REFUSED):
                # Unreachable, or no bridge there: twenty more questions would only
                # time out twenty more times. A refused token still runs the suite,
                # quickly, because the developer wants the full list.
                report = await check_adapter(adapter)
        finally:
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        return outcome(address, cause=cause, report=report, capabilities=capabilities)


async def diagnose(adapter: Any) -> tuple[str | None, list[str]]:
    """The one cause that makes every other finding irrelevant, if there is one.

    Two plain requests: ``/health`` (is a bridge there at all?) and one page of
    products (does it accept the token?). Returns the cause and the capabilities
    the shop declared, which the screen shows after a clean check.
    """
    try:
        health = await adapter.health()
    except (AdapterUnavailableError, AdapterTimeoutError):
        return UNREACHABLE, []
    except AdapterError:
        return NO_BRIDGE, []

    capabilities = sorted(c.value for c in health.capabilities)
    if not health.ok:
        detail = str(health.detail or "")
        return (NO_BRIDGE if detail.startswith("no interface") else NOT_OK), capabilities

    try:
        await adapter.search_products(ProductQuery(limit=1))
    except AdapterAuthError:
        return TOKEN_REFUSED, capabilities
    except AdapterError:
        return None, capabilities  # the suite names it properly
    return None, capabilities


def outcome(
    address: str,
    *,
    cause: str | None,
    report: ConformanceReport | None = None,
    capabilities: list[str] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """What ``shop_checks.result`` holds: findings and counts, never a token."""
    findings = [] if report is None else report.findings
    passed = [] if report is None else list(report.passed_checks)
    errors = sum(1 for f in findings if f.severity is Severity.ERROR)
    warnings = sum(1 for f in findings if f.severity is Severity.WARNING)
    return {
        "cause": cause,
        "message": message,
        "passed": len(passed),
        "failed": errors,
        "warnings": warnings,
        # Only a full run with no errors and nothing standing in its way may
        # connect a shop (ADR-0052 §5).
        "conformant": report is not None and cause is None and errors == 0,
        "capabilities": capabilities or [],
        "findings": [
            {"check": f.check, "severity": f.severity.value, "message": f.message, "hint": f.hint}
            for f in findings
        ],
        "passed_checks": passed,
        "text": developer_text(address, cause, report, message),
    }


#: What the developer's copy says when the check could not run at all.
_CAUSE_LINES = {
    UNREACHABLE: "Could not reach the address: no answer, or the connection was refused.",
    NO_BRIDGE: "Something answered, but there is no bridge at this address (GET /health did not answer as the format says).",
    NOT_OK: 'GET /health answered, but its "status" is not "ok", so NEURA treats the shop as down.',
    TOKEN_REFUSED: "The bridge refused the shop token (HTTP 401 or 403). Put the token from the dashboard in the bridge's settings. Every failure below has this one cause.",
    NO_TOKEN: "There is no shop token to check with. Make one in the dashboard first.",
}


def developer_text(
    address: str, cause: str | None, report: ConformanceReport | None, message: str | None
) -> str:
    """The full result as plain text, for *Copy the full check for your developer*.

    The same marks and words as the terminal tool, problems first. **No line
    points at a file the developer does not have** (G17).
    """
    lines = [f"NEURA check · {address} · {datetime.now(UTC):%Y-%m-%d %H:%M} UTC", ""]
    if cause == ADDRESS_REFUSED:
        lines.append(f"Not checked: {message}")
    elif cause in _CAUSE_LINES:
        lines.append(_CAUSE_LINES[cause])
    if report is not None:
        if cause is not None:
            lines.append("")
        ordered = sorted(report.findings, key=lambda f: f.severity is not Severity.ERROR)
        for finding in ordered:
            mark = "✘" if finding.severity is Severity.ERROR else "⚠"
            lines.append(f"{mark} {finding.check:<28} {finding.message}")
            if finding.hint:
                lines.append(f"    → {finding.hint}")
        for check in report.passed_checks:
            lines.append(f"✔ {check:<28} ok")
        errors = len(report.errors)
        lines += [
            "",
            f"{len(report.passed_checks)} passed · {errors} failed · {len(report.warnings)} warning(s)",
        ]
    return "\n".join(lines)
