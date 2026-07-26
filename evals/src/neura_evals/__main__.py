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
    return parser


async def _run(args: argparse.Namespace) -> int:
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
