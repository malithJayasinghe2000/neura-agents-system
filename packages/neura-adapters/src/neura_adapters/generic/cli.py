"""``neura-conformance`` — the tool a merchant's developer runs against their own store.

This is the part that decides whether the Generic Commerce Interface is a spec
or an *adoptable* spec. A developer implements nine endpoints, runs this, fixes
what it names, and is integrated — no support ticket, no call with us
(docs/architecture/commerce-integration.md §4.2).

Which is why every failure prints a fix, not just a verdict, and why
``--self-test`` exists: a developer must be able to tell "my store is wrong"
from "your tool is broken" without asking anyone.

    uv run neura-conformance --url https://store.example.com/neura/v1 --token $TOKEN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from rich.console import Console

from neura_adapters.generic import webhooks
from neura_adapters.generic.adapter import GenericAdapter
from neura_adapters.generic.client import DEFAULT_TIMEOUT_S
from neura_adapters.generic.reference import DEFAULT_TOKEN, ReferenceStore
from neura_adapters.generic.wire import SPEC_VERSION
from neura_commerce import AdapterError, ConformanceReport, Severity, check_adapter
from neura_core import configure_logging

console = Console()

SPEC_DOC = "docs/spec/generic-commerce-interface-v1.md"

#: Report order. Connectivity and authentication first — if those are wrong,
#: nothing below them matters, and the security finding must not be buried
#: under a list of green ticks.
CHECK_ORDER = (
    "health",
    "health.anonymous",
    "health.content_type",
    "health.spec_version",
    "auth.required",
    "auth.rejects_wrong_token",
    "products.get_missing",
    "products.search_empty",
    "products.search_no_match",
    "products.canonical_status",
    "products.status_vocabulary",
    "pagination",
    "pagination.limit",
    "sync.updated_since",
    "orders.get_missing",
    "orders.canonical_status",
    "orders.status_vocabulary",
    "errors.not_found",
    "customers.get_missing",
    "policies",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neura-conformance",
        description=(
            f"Check a store against the Neura Generic Commerce Interface v{SPEC_VERSION}."
        ),
    )
    parser.add_argument(
        "--url", help="Base URL of the interface, e.g. https://shop.example.com/neura/v1"
    )
    parser.add_argument("--token", help="Bearer token issued for this store.")
    parser.add_argument(
        "--tenant-id",
        default="tn_conformance",
        help="Tenant the fetched entities are attributed to. Any value works for a check.",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="Seconds per request."
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output, for CI.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run against a built-in conformant store to verify this tool itself.",
    )
    parser.add_argument(
        "--webhook-example",
        action="store_true",
        help="Print a correctly signed webhook request to compare your sender against.",
    )
    parser.add_argument("--secret", help="Webhook signing secret, for --webhook-example.")
    return parser


# ── Running ──────────────────────────────────────────────────────────────────


async def check_store(adapter: GenericAdapter) -> ConformanceReport:
    """Both suites, one report.

    The shared adapter suite proves the store behaves like a commerce platform;
    the HTTP checks prove it behaves like *this interface*. Neither alone is
    enough to integrate. The same function the dashboard's *Check* runs
    (ADR-0052 §4), with the token the adapter was built with.
    """
    return await check_adapter(adapter)


def _print_report(report: ConformanceReport, *, url: str) -> None:
    console.print()
    console.print(f"[bold]Neura Generic Commerce Interface — conformance v{SPEC_VERSION}[/]")
    console.print(f"[dim]{url}[/]\n")

    findings = {finding.check: finding for finding in report.findings}
    passed = set(report.passed_checks)
    ordered = [c for c in CHECK_ORDER if c in findings or c in passed]
    ordered += sorted((findings.keys() | passed) - set(ordered))

    for check in ordered:
        finding = findings.get(check)
        if finding is None:
            console.print(f"  [green]✔[/] {check:<28} [dim]ok[/]")
            continue

        mark = "[red]✘[/]" if finding.severity is Severity.ERROR else "[yellow]⚠[/]"
        console.print(f"  {mark} {check:<28} {finding.message}")
        if finding.hint:
            console.print(f"      [dim]→ {finding.hint}[/]")

    errors = len(report.errors)
    warnings = len(report.warnings)
    console.print(
        f"\n  {len(report.passed_checks)} passed · {errors} failed · {warnings} warning(s)\n"
    )

    if report.is_conformant:
        console.print("[green]  Conformant.[/] This store can be connected.")
        if warnings:
            console.print(
                "[yellow]  Warnings are not blocking, but each one is a worse answer "
                "to a real customer question.[/]"
            )
    else:
        console.print("[red]  Not yet conformant.[/]")
    console.print(f"[dim]  Spec: {SPEC_DOC}[/]\n")


def _as_json(report: ConformanceReport) -> str:
    return json.dumps(
        {
            "conformant": report.is_conformant,
            "spec_version": SPEC_VERSION,
            "platform": report.platform,
            "passed": report.passed_checks,
            "findings": [
                {
                    "check": f.check,
                    "severity": f.severity.value,
                    "message": f.message,
                    "hint": f.hint,
                }
                for f in report.findings
            ],
        },
        indent=2,
    )


async def _run_against(
    *, url: str, token: str | None, tenant_id: str, timeout_s: float, transport: Any = None
) -> ConformanceReport:
    adapter = GenericAdapter(
        base_url=url,
        tenant_id=tenant_id,
        token=token,
        timeout_s=timeout_s,
        transport=transport,
    )
    try:
        return await check_store(adapter)
    finally:
        await adapter.aclose()


async def _self_test(args: argparse.Namespace) -> int:
    """Prove the tool works, then prove it can fail.

    A checker that has only ever been run against a correct store is a checker
    nobody has tested. This runs both directions, for the same reason the eval
    judge check does (evals/src/neura_evals/__main__.py).
    """
    from neura_adapters.generic.reference import Defect

    store = ReferenceStore()
    good = await _run_against(
        url=store.base_url(),
        token=DEFAULT_TOKEN,
        tenant_id=args.tenant_id,
        timeout_s=args.timeout,
        transport=store.transport(),
    )

    broken_store = ReferenceStore(defects=frozenset({Defect.NO_AUTH, Defect.MISSING_AS_200}))
    broken = await _run_against(
        url=broken_store.base_url(),
        token=DEFAULT_TOKEN,
        tenant_id=args.tenant_id,
        timeout_s=args.timeout,
        transport=broken_store.transport(),
    )

    _print_report(good, url="built-in reference store")

    accepts_good = good.is_conformant
    rejects_bad = not broken.is_conformant

    console.print(f"  {'[green]✔[/]' if accepts_good else '[red]✘[/]'} accepts a conformant store")
    console.print(
        f"  {'[green]✔[/]' if rejects_bad else '[red]✘[/]'} rejects a store that serves "
        f"orders without a token"
    )
    console.print()

    if accepts_good and rejects_bad:
        console.print("[green]  This tool is working. A failure below is your store, not us.[/]\n")
        return 0
    console.print("[red]  This tool is not behaving correctly — please report it.[/]\n")
    return 1


def _webhook_example(secret: str) -> int:
    """A correctly signed request, so a sender can be compared byte for byte.

    Signature mismatches are otherwise near-impossible to debug from the
    receiving end: every failure looks identical from the outside.
    """
    body = json.dumps(
        {"event": "order.updated", "external_id": "1001", "occurred_at": "2026-07-26T10:00:00Z"},
        separators=(", ", ": "),
    ).encode()
    signature, timestamp = webhooks.sign(body, secret)

    console.print("\n[bold]A correctly signed webhook request[/]\n")
    console.print("  POST {your_neura_webhook_url}")
    console.print("  Content-Type: application/json")
    console.print(f"  {webhooks.TIMESTAMP_HEADER}: {timestamp}")
    # soft_wrap: a wrapped signature or body is one a developer cannot compare
    # against their own output, which is the entire point of printing it.
    console.print(f"  {webhooks.SIGNATURE_HEADER}: {signature}", soft_wrap=True)
    console.print(f"\n  {body.decode()}\n", soft_wrap=True)
    console.print(
        "[dim]  Signed value is the raw body prefixed with the timestamp and a dot:\n"
        f"    {timestamp}.<raw body bytes>\n"
        "  HMAC-SHA256, hex digest. Sign the bytes you send — re-serialising parsed\n"
        f"  JSON changes key order and the signature stops matching.\n"
        f"  Requests more than {webhooks.DEFAULT_TOLERANCE_S}s old are rejected.[/]\n"
    )
    return 0


async def _run(args: argparse.Namespace) -> int:
    if args.webhook_example:
        if not args.secret:
            console.print("[red]--webhook-example needs --secret[/]")
            return 2
        return _webhook_example(args.secret)

    if args.self_test:
        return await _self_test(args)

    if not args.url:
        console.print("[red]--url is required[/] (or use --self-test)")
        return 2

    try:
        report = await _run_against(
            url=args.url,
            token=args.token,
            tenant_id=args.tenant_id,
            timeout_s=args.timeout,
        )
    except AdapterError as exc:
        # Reaching here means we could not talk to the store at all — a wrong
        # URL or a firewall, not a conformance failure. Saying "not conformant"
        # would send the developer to debug the wrong thing.
        console.print(f"\n[red]  Could not check {args.url}[/]\n  {exc}\n")
        return 2

    if args.json:
        print(_as_json(report))
    else:
        _print_report(report, url=args.url)

    return 0 if report.is_conformant else 1


def main() -> None:
    # The report is the output. Our own INFO logs interleaved with it would
    # make a developer read our internals instead of their findings.
    configure_logging(level="ERROR", json_output=False)
    args = _build_parser().parse_args()
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
