"""CLI: ``uv run neura-eval`` / ``make eval``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from neura_evals.config import judge_from_env
from neura_evals.dataset import load_all, load_dataset
from neura_evals.judge import Judge
from neura_evals.report import print_report
from neura_evals.runner import DEFAULT_CONCURRENCY, dataset_dir, run_eval
from neura_evals.target import NotImplementedTarget


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neura-eval",
        description="Run the agent evaluation suite.",
    )
    parser.add_argument(
        "--dataset",
        help="Dataset name (without .yaml). Omit to run every dataset.",
    )
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=None,
        help="Directory of dataset YAML files.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="Parallel cases. Keep low on a rate-limited free judge tier.",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip judged metrics. Mechanical checks only — no API calls, no cost.",
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit non-zero if any gate is not met. Used by CI.",
    )
    parser.add_argument(
        "--check-judge",
        action="store_true",
        help="Verify the judge is reachable and actually catches a hallucination, then exit.",
    )
    return parser


async def _check_judge() -> int:
    """Prove the judge works before trusting a single score from it.

    Deliberately tests both directions. A judge that passes everything looks
    identical to a working one until it silently approves a hallucination.
    """
    from rich.console import Console

    console = Console()
    config = judge_from_env()
    judge = Judge(config)

    console.print()
    console.print(f"  model   {config.model}")
    console.print(f"  trust   {config.trust.value}")
    if not config.is_trusted:
        console.print(
            "\n  [yellow]⚠ This judge is not trusted. Scores from it are directional at best.[/]"
            "\n    Set EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY / EVAL_JUDGE_MODEL.[/]"
        )
    console.print()

    evidence = "Order 1001: status=shipped, shipped_at=2026-07-22, tracking=TRK123456"

    grounded = await judge.grounded(
        reply="Your order #1001 shipped on 22 July, tracking TRK123456.", evidence=evidence
    )
    hallucinated = await judge.grounded(
        reply="Your order arrived yesterday and your neighbour signed for it.", evidence=evidence
    )

    ok_true = grounded.passed
    ok_false = not hallucinated.passed

    console.print(
        f"  {'[green]✔[/]' if ok_true else '[red]✘[/]'} accepts a grounded reply    "
        f"score={grounded.score}"
    )
    console.print(
        f"  {'[green]✔[/]' if ok_false else '[red]✘[/]'} rejects a hallucination     "
        f"score={hallucinated.score}"
    )
    if hallucinated.unsupported_claims:
        for claim in hallucinated.unsupported_claims:
            console.print(f"        caught: {claim!r}")

    console.print()
    if ok_true and ok_false:
        console.print("[green]  Judge is working.[/]\n")
        return 0
    console.print("[red]  Judge is not behaving correctly — do not trust its scores.[/]\n")
    return 1


async def _run(args: argparse.Namespace) -> int:
    if args.check_judge:
        return await _check_judge()

    directory = args.datasets_dir or dataset_dir()
    if not directory.exists():
        print(f"No dataset directory at {directory}", file=sys.stderr)
        return 1

    if args.dataset:
        path = directory / f"{args.dataset}.yaml"
        if not path.exists():
            print(f"No dataset named {args.dataset!r} in {directory}", file=sys.stderr)
            return 1
        datasets = [load_dataset(path)]
    else:
        datasets = load_all(directory)

    if not datasets:
        print(f"No datasets found in {directory}", file=sys.stderr)
        return 1

    judge = None if args.no_judge else Judge(judge_from_env())

    # The agent does not exist yet (milestone 1.11). Until it does, this target
    # returns an explicit error rather than a plausible empty response, so a run
    # cannot be mistaken for a real result.
    target = NotImplementedTarget()

    report = await run_eval(
        target=target,
        datasets=datasets,
        judge=judge,
        concurrency=args.concurrency,
    )
    print_report(report)

    if args.fail_on_gate and report.summary.gate_failures():
        return 1
    return 0


def main() -> None:
    args = _build_parser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
