"""Terminal reporting.

The report leads with **caveats**, not scores. A number produced by an untrusted
judge, or over invented test cases, looks identical to a real measurement — and
that resemblance is exactly how a project ends up quoting its own guesses back to
itself. See CLAUDE.md §4.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from neura_evals.metrics import LOWER_IS_BETTER, THRESHOLDS, CaseOutcome, RunSummary
from neura_evals.runner import RunReport, RunVerdict, compare

console = Console()


def print_report(report: RunReport, verdict: RunVerdict | None = None) -> None:
    console.print()
    console.rule(f"[bold]Eval — {report.target_name}")

    _print_caveats(report)

    summary = report.summary
    # Four counts, not two. `total - passed` was the arithmetic behind Finding
    # 27's headline — with 47 cases unreachable it printed `47 passed, 0 failed`
    # directly under a panel saying 47 of 47 had reached no model (E9).
    #
    # `errored` and `skipped` are printed only when non-zero, so an ordinary
    # green run reads exactly as it always has.
    parts = [f"[green]{summary.passed} passed[/]", f"[red]{summary.failed} failed[/]"]
    if summary.errored:
        parts.append(f"[magenta]{summary.errored} errored[/]")
    if summary.skipped:
        parts.append(f"[yellow]{summary.skipped} skipped[/]")
    console.print(f"\n  cases       {summary.total}  ({', '.join(parts)})")
    if summary.errored or summary.skipped:
        console.print(
            f"  [dim]measured    {summary.measured} of {summary.total} — "
            "errored and skipped cases were never measured and are not results[/]"
        )
    console.print(f"  datasets    {', '.join(report.datasets)}")
    trust_label = f" [{report.judge_trust.value}]" if report.judge_trust else " (skipped)"
    console.print(f"  judge       {report.judge_model}{trust_label}")
    console.print(f"  duration    {report.duration_s}s\n")

    if summary.metrics:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("metric")
        table.add_column("value", justify="right")
        table.add_column("gate", justify="right")
        table.add_column("", width=3)
        # How much of the run each rate was asked about. A gate met on one case
        # of fourteen prints identically to one met on all fourteen unless the
        # column is here — which is what SELL's 2026-08-26 tool selection figure
        # did, and it was the run's only unmeasured case that had failed.
        table.add_column("cases", justify="right")

        for name, value in sorted(summary.metrics.items()):
            threshold = THRESHOLDS.get(name)
            if threshold is None:
                mark, gate = "", "—"
            else:
                breached = value > threshold if name in LOWER_IS_BETTER else value < threshold
                mark = "[red]✘[/]" if breached else "[green]✔[/]"
                gate = f"{threshold:.2f}"
            measured, scoreable = summary.coverage.get(name, (0, 0))
            covered = f"{measured}/{scoreable}"
            if scoreable and measured < scoreable:
                covered = f"[yellow]{covered}[/]"
            table.add_row(name.replace("_", " "), f"{value:.2f}", gate, mark, covered)

        console.print(table)
        console.print(
            "  [dim]cases = how many of the cases that ran actually scored that metric. "
            "A rate over part of a suite is real, and narrower than it looks.[/]"
        )

    _print_dispatch_matrix(summary)

    console.print(
        f"\n  latency     p50 {summary.p50_latency_ms}ms · p95 {summary.p95_latency_ms}ms"
    )
    console.print(f"  cost        ${summary.total_cost_usd}\n")

    _print_errors(report)

    # `r.failed`, not `not r.passed`. The difference is the point: an errored
    # case is listed under Errors above, in its own colour, and never among the
    # agent's failures.
    failures = [r for r in report.results if r.failed]
    if failures:
        console.print("[bold red]Failures[/]  [dim]— the agent got these wrong[/]\n")
        for result in failures[:20]:
            console.print(f"  [red]✘[/] {result.case_id}  [dim]({result.intent})[/]")
            for check in result.failures:
                console.print(f"      {check.name}: {check.detail}")

            # The draft, for failed cases only (open question E7). Without it a
            # failure can only be diagnosed by re-running the whole suite and
            # hoping it reproduces — which on 2026-08-02 meant a twenty-minute
            # run against a model server that had already crashed three times.
            #
            # Only on failures: printing every draft would bury the signal, and
            # the drafts that matter are the ones somebody is about to
            # investigate.
            if draft := result.response.draft.strip():
                console.print(f"      [dim]draft:  {draft[:220]}[/]")
            if reason := result.response.verify_reason.strip():
                console.print(f"      [dim]verify: {reason[:160]}[/]")
            # For the turns that never reached `verify` — the ones where every
            # other diagnostic field is empty and only this one says anything.
            if reason := result.response.escalation_reason.strip():
                console.print(f"      [dim]escalated: {reason[:160]}[/]")
        if len(failures) > 20:
            console.print(f"\n  ... and {len(failures) - 20} more")
        console.print()

    gate_failures = summary.gate_failures()
    if gate_failures:
        lines = [
            f"{name.replace('_', ' ')}  {actual:.2f}  (gate {threshold:.2f})"
            for name, actual, threshold in gate_failures
        ]
        console.print(
            Panel("\n".join(lines), title="[red]Gates not met", border_style="red", expand=False)
        )

    _print_verdict(verdict)


def _print_verdict(verdict: RunVerdict | None) -> None:
    """What the process is about to exit with, and why.

    Printed last and printed always, because the failure E9 records is a run
    whose warnings were all correct and whose exit code was 0. A reader should
    not have to reconstruct the verdict from four panels.
    """
    if verdict is None:
        return

    if verdict.ok:
        if verdict.required:
            console.print(
                f"  [green]✔ run OK[/]  [dim]required: "
                f"{', '.join(n.replace('_', ' ') for n in verdict.required)}[/]\n"
            )
        return

    console.print(
        Panel(
            "\n".join(f"• {reason}" for reason in verdict.reasons),
            title=f"[red]RUN FAILED — exit {verdict.exit_code}",
            border_style="red",
            expand=False,
        )
    )


def _print_errors(report: RunReport) -> None:
    """Cases that never produced a result, kept away from the agent's failures.

    Separate section, separate colour, separate word. Finding 27's report had
    every one of these and called them passes.
    """
    errored = [r for r in report.results if r.outcome is CaseOutcome.ERRORED]
    if not errored:
        return

    console.print(
        "[bold magenta]Errors[/]  [dim]— these never reached a result. Not agent failures.[/]\n"
    )
    for result in errored[:10]:
        detail = result.response.infrastructure_error or result.response.error or "unknown"
        console.print(f"  [magenta]![/] {result.case_id}  [dim]({result.intent})[/]")
        console.print(f"      {detail[:200]}")
    if len(errored) > 10:
        console.print(f"\n  ... and {len(errored) - 10} more")
    console.print()


def _print_dispatch_matrix(summary: RunSummary) -> None:
    """Which agent each message was meant for, and which one got it — [ADR-0031].

    Printed beside `dispatch_accuracy` because the rate alone cannot say which
    way the run was wrong, and the two directions do not cost the same. Silent
    when nothing dispatched, so an ordinary agent suite is unchanged.
    """
    if not summary.dispatch_matrix:
        return

    console.print("\n  [bold]dispatch[/]  [dim]expected → chosen[/]")
    for expected in sorted(summary.dispatch_matrix):
        chosen = summary.dispatch_matrix[expected]
        for got in sorted(chosen, key=lambda k: (k != expected, k)):
            count = chosen[got]
            if got == expected:
                console.print(f"    [green]✔[/] {expected} → {got}  [dim]x{count}[/]")
            else:
                console.print(f"    [red]✘[/] {expected} → [red]{got}[/]  [dim]x{count}[/]")
    console.print(
        "  [dim]a misroute is not symmetric: one direction loses a feature, the other "
        "hands the shopper to a person. The rate above cannot tell you which.[/]"
    )


def _print_caveats(report: RunReport) -> None:
    """Say plainly what these numbers are not."""
    warnings: list[str] = []

    # Said first and said loudly. With every case skipped there are no failed
    # checks, so the summary line reads "35 passed" — which is true of the
    # checks and false of everything a reader would infer from it.
    #
    # Keyed on the measurement, not on the target's *name*. It used to test
    # `target_name == "no-agent"`, which silently covered exactly one target:
    # the first target that was neither an agent nor `--no-agent` printed
    # "16 passed, 0 failed" with no caveat (found 2026-08-30, ADR-0031 §6).
    # A name is not a measurement — the same lesson `coverage` already carries.
    if report.summary.errored:
        # Said first and said loudly, above every other caveat — which is what
        # this comment claimed before 2026-09-06 while the block sat fourth, so
        # a reader met "the judge was skipped" before "no case reached a model".
        #
        # A run that lost cases to a dead model server is not a weak result — it
        # is not a result. Measured 2026-07-31: Ollama died mid-run, the graph
        # degraded correctly to escalation on every case, and the suite reported
        # intent accuracy 0.00. Nothing about the agent had changed.
        everything = report.summary.errored == report.summary.total
        headline = (
            "[bold]NOTHING WAS MEASURED. No case reached a result.[/]"
            if everything
            else f"[bold]{report.summary.errored} of {report.summary.total} cases "
            "never reached a result.[/]"
        )
        warnings.append(
            f"{headline}\n"
            "They are ERRORED — neither passed nor failed, because they were never\n"
            "measured. Every metric below covers only the cases that did run, so it is\n"
            "real and narrower than it looks. Check the provider is up and re-run before\n"
            "comparing this against anything."
        )

    if report.summary.unmeasured and report.summary.unmeasured == report.summary.total:
        reason = next(
            (r.response.error for r in report.results if r.response.error),
            "no target was run",
        )
        warnings.append(
            "[bold]NOTHING WAS RUN. Nothing here measures anything.[/]\n"
            f"{reason}\n"
            "Every case was skipped. This run proves the datasets parse and the scoring\n"
            "logic works — it says nothing about whether any reply was correct, grounded\n"
            "or safe."
        )
    elif report.summary.unmeasured:
        warnings.append(
            f"[bold]{report.summary.unmeasured} of {report.summary.total} cases did not run.[/]\n"
            "They are skipped, not failed — but every rate below covers only the rest."
        )

    if not report.judge_enabled:
        warnings.append(
            "[bold]Judged metrics were skipped (--no-judge).[/]\n"
            "Groundedness and relevance were not measured. The mechanical checks\n"
            "below are still valid; there is simply no evidence here about whether\n"
            "replies were truthful."
        )
    elif not report.scores_are_trustworthy:
        trust = report.judge_trust.value if report.judge_trust else "unknown"
        warnings.append(
            "[bold]Judged scores are NOT trustworthy.[/]\n"
            f"The judge is {report.judge_model} ({trust}).\n"
            "A weak model grading a weak model produces numbers that look like\n"
            "measurements and are not. Set EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY /\n"
            "EVAL_JUDGE_MODEL to a strong model before quoting anything from this run."
        )

    if report.summary.unavailable:
        # The subset of `errored` whose cause was the provider specifically,
        # rather than a target that raised. Named separately because the two
        # need different people: one restarts Ollama, the other reads a stack.
        warnings.append(
            f"[bold]{report.summary.unavailable} of {report.summary.total} cases could not "
            "reach the model provider.[/]\n"
            "Rate limit, quota or outage. `make eval` and `make eval-guard-off` exit 3 on\n"
            "this rather than 0 — a suite that measured nothing must not report green."
        )

    if report.summary.unjudged:
        warnings.append(
            f"[bold]{report.summary.unjudged} case(s) could not be judged.[/]\n"
            "The judge was unreachable — rate limit, quota or outage. Those cases are\n"
            "EXCLUDED from groundedness rather than counted against the agent, so the\n"
            "figure above is real but covers less of the suite than it looks like.\n"
            "A free judge tier will do this: re-run later, or move to a paid tier."
        )

    if report.summary.total and not report.is_validation:
        warnings.append(
            "[bold]Every case in this run is synthetic.[/]\n"
            "Invented cases test what we expect to happen — which is the wrong thing\n"
            "to measure. This run proves the harness works, not that the agent does.\n"
            "Replace with real conversations before treating any score as validation."
        )

    for warning in warnings:
        console.print(Panel(warning, border_style="yellow", expand=False))


def print_comparison(baseline: RunReport, candidate: RunReport) -> None:
    """Side-by-side. What makes a model swap a decision rather than a gamble."""
    console.print()
    console.rule("[bold]Comparison")
    console.print(f"\n  {baseline.target_name}  →  {candidate.target_name}\n")

    if not (baseline.scores_are_trustworthy and candidate.scores_are_trustworthy):
        console.print(
            Panel(
                "[bold]At least one run used an untrusted judge.[/]\n"
                "A delta between two unreliable measurements is not evidence.",
                border_style="yellow",
                expand=False,
            )
        )

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("metric")
    table.add_column(baseline.target_name, justify="right")
    table.add_column(candidate.target_name, justify="right")
    table.add_column("delta", justify="right")
    table.add_column("", width=3)

    regressions = 0
    for name, before, after, delta in compare(baseline, candidate):
        improved = delta < 0 if name in LOWER_IS_BETTER else delta > 0
        if abs(delta) < 1e-9:
            mark, colour = "[dim]—[/]", "dim"
        elif improved:
            mark, colour = "[green]✔[/]", "green"
        else:
            mark, colour = "[yellow]⚠[/]", "yellow"
            regressions += 1
        table.add_row(
            name.replace("_", " "),
            f"{before:.2f}",
            f"{after:.2f}",
            f"[{colour}]{delta:+.2f}[/]",
            mark,
        )

    console.print(table)
    console.print(
        f"\n  latency p95   {baseline.summary.p95_latency_ms}ms → "
        f"{candidate.summary.p95_latency_ms}ms"
    )
    console.print(
        f"  cost          ${baseline.summary.total_cost_usd} → "
        f"${candidate.summary.total_cost_usd}\n"
    )

    if regressions:
        console.print(f"[yellow]⚠ {regressions} regression(s). Review before promoting.[/]\n")
