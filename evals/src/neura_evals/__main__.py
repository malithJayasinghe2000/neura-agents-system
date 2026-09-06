"""CLI: ``uv run neura-eval`` / ``make eval``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from neura_core import load_env
from neura_evals.config import judge_from_env
from neura_evals.dataset import Dataset, load_all, load_dataset
from neura_evals.discovery import DiscoveredAgent, discover_agents
from neura_evals.judge import Judge
from neura_evals.metrics import REPORTED_METRICS
from neura_evals.persist import default_path, write_report
from neura_evals.report import print_report
from neura_evals.runner import DEFAULT_CONCURRENCY, judge_run, run_eval
from neura_evals.target import EvalTarget, NotImplementedTarget

#: The role map an eval runs under, unless told otherwise. Local by default so
#: the suite costs nothing to run; `--role-map cloud-prod` is how the comparison
#: in llm-abstraction.md §8 gets produced.
DEFAULT_ROLE_MAP = "ollama-dev"

#: Sentinel for ``--out`` with no value. A real path cannot be chosen at parse
#: time because the default name contains the agent, which ``--agent`` may not
#: have named — it is resolved after discovery.
_DEFAULT_OUT = Path("-")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neura-eval",
        description="Run the agent evaluation suite.",
    )
    parser.add_argument(
        "--agent",
        help="Which installed agent to evaluate. Omit when only one is installed.",
    )
    parser.add_argument(
        "--role-map",
        default=DEFAULT_ROLE_MAP,
        help=f"LLM role map to run under (default: {DEFAULT_ROLE_MAP}).",
    )
    parser.add_argument(
        "--dataset",
        help="Dataset name (without .yaml). Omit to run every dataset.",
    )
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=None,
        help="Directory of dataset YAML files. Overrides the agent's own.",
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
        "--no-agent",
        action="store_true",
        help=(
            "Do not run an agent. Validates the datasets and the harness only; "
            "every case reports an execution error, by design."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Write the whole run to this JSON file — every case, its draft, the "
            "verifier's reason and the evidence it was written from (open question E7). "
            "Pass --out with no value to use evals/reports/<agent>-<timestamp>.json."
        ),
        nargs="?",
        const=_DEFAULT_OUT,
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit 1 if ANY gate is not met, required or not. Opt-in.",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="METRIC",
        help=(
            "A metric this run must PRODUCE, and must meet the gate for. Repeatable. "
            "A required metric that was never measured fails the run (exit 1) — the "
            "gap open question E9 records, where `injection_resistance` was absent "
            "rather than 0.00 and the run exited 0."
        ),
    )
    parser.add_argument(
        "--fail-on-unmeasured",
        action="store_true",
        help=(
            "Exit 3 if any case never reached a result — provider unreachable, rate "
            "limited, or the target raised. A partial suite is not comparable with a "
            "full one, and a suite that measured nothing is not a result at all."
        ),
    )
    parser.add_argument(
        "--list-agents",
        action="store_true",
        help="Show which installed agents can be evaluated, then exit.",
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
            "\n[yellow]  ⚠ This judge is not trusted. Its scores are directional at best."
            "\n    Set EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY / EVAL_JUDGE_MODEL in .env.[/]"
        )
    console.print()

    evidence = "Order 1001: status=shipped, shipped_at=2026-07-22, tracking=TRK123456"

    grounded = await judge.grounded(
        reply="Your order #1001 shipped on 22 July, tracking TRK123456.", evidence=evidence
    )
    hallucinated = await judge.grounded(
        reply="Your order arrived yesterday and your neighbour signed for it.", evidence=evidence
    )

    # `available` is checked first, and it is not a formality. An unreachable
    # judge returns passed=False, which satisfies "rejects a hallucination"
    # perfectly — so a completely dead judge used to print a green tick next to
    # the check that matters most. A judge that is down must never look like a
    # judge that is working.
    reachable = grounded.available and hallucinated.available
    ok_true = reachable and grounded.passed
    ok_false = reachable and not hallucinated.passed

    if not reachable:
        detail = grounded.reasoning if not grounded.available else hallucinated.reasoning
        console.print("[red]  ✘ the judge could not be reached at all[/]")
        console.print(f"    {detail[:300]}\n")

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


def _list_agents() -> int:
    agents = discover_agents()
    if not agents:
        print("No installed agent advertises a 'neura.eval_targets' entry point.")
        return 1
    for agent in agents:
        count = len(list(agent.dataset_dir.glob("*.yaml")))
        print(f"  {agent.key:<12} {count} dataset(s)  {agent.dataset_dir}")
    return 0


def _select_agent(requested: str | None) -> DiscoveredAgent | None:
    """Pick the agent to evaluate, or explain why none can be."""
    agents = discover_agents()

    if not agents:
        return None

    if requested:
        for agent in agents:
            if agent.key == requested:
                return agent
        print(
            f"No installed agent named {requested!r}. Found: {', '.join(a.key for a in agents)}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if len(agents) > 1:
        # Refuse rather than pick. Silently evaluating one agent when the user
        # meant another produces a number that is real, plausible, and about the
        # wrong thing.
        print(
            "Several agents are installed — choose one with --agent: "
            f"{', '.join(a.key for a in agents)}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    return agents[0]


def _load_datasets(directory: Path, name: str | None) -> list[Dataset]:
    if not directory.exists():
        print(f"No dataset directory at {directory}", file=sys.stderr)
        raise SystemExit(1)

    if name:
        path = directory / f"{name}.yaml"
        if not path.exists():
            print(f"No dataset named {name!r} in {directory}", file=sys.stderr)
            raise SystemExit(1)
        return [load_dataset(path)]

    datasets = load_all(directory)
    if not datasets:
        print(f"No datasets found in {directory}", file=sys.stderr)
        raise SystemExit(1)
    return datasets


def _build_target(agent: DiscoveredAgent | None, role_map: str, no_agent: bool) -> EvalTarget:
    """The thing being measured.

    Falls back to ``NotImplementedTarget`` when no agent is available, and that
    fallback returns an explicit error for every case rather than a plausible
    empty response — a run against nothing must not be mistakable for a result.
    """
    if no_agent or agent is None:
        return NotImplementedTarget()

    from neura_llm import LLMClient

    return agent.build(LLMClient.from_role_map_name(role_map))


async def _run(args: argparse.Namespace, *, target: EvalTarget | None = None) -> int:
    """One run, start to exit code.

    ``target`` is injectable so the exit-code paths can be tested against a
    deterministic stub rather than by taking a model server away — which is not
    a thing an automated test may depend on, and is how E9 was found rather than
    how it should be reproduced.
    """
    if args.check_judge:
        return await _check_judge()
    if args.list_agents:
        return _list_agents()

    # Discovered even under --no-agent: that flag suppresses *running* the agent,
    # not finding its datasets. Validating the cases without spending a single
    # model call is exactly what `make check` wants.
    agent = _select_agent(args.agent)

    if agent is None:
        print(
            "No installed agent advertises a 'neura.eval_targets' entry point — "
            "running the harness against nothing. Every case will report an "
            "execution error, which is correct and is not a result.",
            file=sys.stderr,
        )

    directory = args.datasets_dir or (agent.dataset_dir if agent else None)
    if directory is None:
        print(
            "No datasets to run: no agent was found and --datasets-dir was not given.",
            file=sys.stderr,
        )
        return 1

    datasets = _load_datasets(directory, args.dataset)
    judge = None if args.no_judge else Judge(judge_from_env())
    if target is None:
        target = _build_target(agent, args.role_map, args.no_agent)

    report = await run_eval(
        target=target,
        datasets=datasets,
        judge=judge,
        concurrency=args.concurrency,
    )

    # Decided before anything is printed or written, so the terminal, the file
    # and the exit code cannot disagree. They did on 2026-09-06: the report said
    # 47 of 47 cases reached no model and the process exited 0 (E9).
    verdict = judge_run(
        report,
        required=args.require,
        fail_on_gate=args.fail_on_gate,
        fail_on_unmeasured=args.fail_on_unmeasured,
    )
    print_report(report, verdict)

    # Written whatever the verdict, so a run that exits non-zero still leaves its
    # evidence behind. A failing run is precisely the one somebody will want to
    # read again (E7).
    if args.out is not None:
        out = default_path(target.name) if args.out == _DEFAULT_OUT else args.out
        print(f"  run written to {write_report(report, out, verdict)}\n")

    return verdict.exit_code


def main() -> None:
    # Before anything reads configuration: judge settings live in .env, and
    # os.getenv cannot see a file nobody loaded.
    load_env()
    parser = _build_parser()
    args = parser.parse_args()

    # A `--require` naming a metric this harness cannot emit would be a command
    # that fails for ever for a reason nobody could act on, so a typo is a usage
    # error (argparse's exit 2) rather than a gate failure.
    if unknown := [name for name in args.require if name not in REPORTED_METRICS]:
        parser.error(
            f"unknown metric(s) for --require: {', '.join(sorted(unknown))}. "
            f"Available: {', '.join(sorted(REPORTED_METRICS))}"
        )

    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
