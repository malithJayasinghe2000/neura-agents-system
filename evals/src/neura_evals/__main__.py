"""CLI: ``uv run neura-eval`` / ``make eval``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from neura_core import get_logger, load_env
from neura_evals.config import RoleMapModels, judge_from_env, resolve_judge_trust
from neura_evals.dataset import Dataset, load_all, load_dataset
from neura_evals.discovery import DiscoveredAgent, discover_agents
from neura_evals.judge import Judge, JudgeTrust
from neura_evals.metrics import REPORTED_METRICS
from neura_evals.persist import default_path, write_report
from neura_evals.report import print_report
from neura_evals.runner import DEFAULT_CONCURRENCY, EXIT_UNMEASURED, judge_run, run_eval
from neura_evals.target import EvalTarget, NotImplementedTarget

#: The role map an eval runs under, unless told otherwise. Local by default so
#: the suite costs nothing to run; `--role-map cloud-prod` is how the comparison
#: in llm-abstraction.md §8 gets produced.
DEFAULT_ROLE_MAP = "ollama-dev"

#: Sentinel for ``--out`` with no value. A real path cannot be chosen at parse
#: time because the default name contains the agent, which ``--agent`` may not
#: have named — it is resolved after discovery.
_DEFAULT_OUT = Path("-")

log = get_logger(__name__)


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


async def _check_judge(role_map: str) -> int:
    """Prove the judge works, and say separately whether it *qualifies*.

    **Two questions, kept apart** ([ADR-0037] §6):

    * **Does it function?** Reachable, accepts a grounded reply, catches a
      hallucination. Both directions, because a judge that passes everything
      looks identical to a working one until it approves a fabrication. **This
      is what the exit code reports**, because it is what the command is for.
    * **Does it qualify?** A functioning judge that is one of the models under
      test still cannot produce evidence. Printed, never folded into the tick —
      and it is why this takes ``role_map``: before 2026-09-12 this command
      printed ``trust  trusted`` for a judge grading its own answer, which is
      the one thing it must never say (open question E11).
    """
    from rich.console import Console

    console = Console()
    models = _inspect_role_map(role_map)
    config = resolve_judge_trust(judge_from_env(), models)
    judge = Judge(config)

    console.print()
    console.print(f"  model     {config.model}")
    console.print(f"  endpoint  {config.endpoint or '(unset)'}")
    console.print(f"  trust     {config.trust.value}")
    console.print(f"  vs        role map {role_map} — {models.described}")

    if not models.inspected:
        # Exits before a single judge call. The question "is this judge
        # qualified" has no answer here, and spending API quota to learn that it
        # *functions* would bury the thing the operator has to fix.
        console.print(
            f"\n[red]  ✘ QUALIFICATION UNKNOWN — the role map could not be inspected.[/]"
            f"\n    {models.detail}"
            "\n    Self-judging was NOT ruled out, so this judge may not be treated as"
            "\n    independent. Fix the role map, then re-run.\n"
        )
        return 1

    if config.trust is JudgeTrust.UNTRUSTED_SELF_JUDGING:
        console.print(
            f"\n[red]  ✘ NOT QUALIFIED — {config.model} serves a role in {role_map}.[/]"
            "\n    It would be grading its own answer. Groundedness from this"
            "\n    configuration cannot satisfy `--require groundedness`."
        )
    elif not config.is_trusted:
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
        # Never a bare "Judge is working." when it does not qualify: that reads
        # as approval of the whole arrangement, which is the sentence E11 is
        # about. Functionality decides the exit code; qualification is said out
        # loud beside it.
        if config.trust is JudgeTrust.UNTRUSTED_SELF_JUDGING:
            console.print(
                "[yellow]  Judge is FUNCTIONING but NOT QUALIFIED for this role map.[/]"
                "\n  It answers correctly and it may not be used as evidence.\n"
            )
        elif not config.is_trusted:
            console.print("[yellow]  Judge is functioning; its scores are labelled untrusted.[/]\n")
        else:
            console.print("[green]  Judge is working.[/]\n")
        return 0
    console.print("[red]  Judge is not behaving correctly — do not trust its scores.[/]\n")
    return 1


def _inspect_role_map(role_map: str) -> RoleMapModels:
    """What models does this role map use? Or: say plainly that we could not tell.

    ``--check-judge`` must still report on the judge when the role map cannot be
    built — an unknown name, missing provider configuration — rather than dying
    on the way to the thing the user asked about. **But it must not then call the
    judge independent.** The first version returned ``None`` here, which
    `_models_in_play` turned into an empty set, which the comparison read as
    "matches nothing", which printed `trusted`.
    """
    try:
        llm = _build_client(role_map)
    except Exception as exc:
        log.error("role_map_unavailable", role_map=role_map, error=f"{type(exc).__name__}: {exc}")
        return RoleMapModels(
            inspected=False,
            detail=f"role map {role_map!r} could not be loaded: {type(exc).__name__}: {exc}",
        )
    return _models_in_play(llm)


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


def _build_client(role_map: str) -> Any:
    """The one LLM client for this run.

    Built here rather than inside :func:`_build_target` so that the same client
    both runs the agent and answers *"which models is this run using?"* for the
    self-judging check ([ADR-0037]). Two clients would be two answers, and the
    one that mattered would be the one nobody looked at.
    """
    from neura_llm import LLMClient

    return LLMClient.from_role_map_name(role_map)


def _build_target(agent: DiscoveredAgent | None, llm: Any, no_agent: bool) -> EvalTarget:
    """The thing being measured.

    Falls back to ``NotImplementedTarget`` when no agent is available, and that
    fallback returns an explicit error for every case rather than a plausible
    empty response — a run against nothing must not be mistakable for a result.

    The agent is still reached through its **entry point** — ``agent.build`` came
    from ``neura.eval_targets`` — so this module continues not to know that an
    agent called "care" exists.
    """
    if no_agent or agent is None or llm is None:
        return NotImplementedTarget()

    return agent.build(llm)


def _models_in_play(llm: Any) -> RoleMapModels:
    """Every model the active role map would use, for the self-judging check.

    **Every role, not just the two that touch the graded text.** `REASONER`
    writes the reply and `GUARD` has already ruled it grounded, so those are the
    two that bias a verdict — but comparing against all of them is fail-closed,
    always includes both, and costs nothing.

    **Only `RoleNotConfiguredError` means "this role is not configured".** It is
    what `RoleMap.resolve()` raises for all three legitimate cases — an undefined
    role, an unknown provider, an unset environment variable — so anything else
    is a defect, and the first version of this function swallowed every one of
    them into an empty set that then read as *trusted*. An unexpected failure now
    returns ``inspected=False``, which is non-qualifying rather than silent.

    Never raises: a run whose mechanical metrics are valid should not be
    destroyed because the *judge qualification* could not be worked out. It is
    reported as unknown instead, and unknown satisfies nothing.
    """
    if llm is None:
        # Known-empty: nothing ran, so nothing was self-judged.
        return RoleMapModels()

    from neura_llm import ModelRole, RoleNotConfiguredError

    found: set[str] = set()
    for role in ModelRole:
        try:
            found.add(str(llm.model_for(role)))
        except RoleNotConfiguredError as exc:
            log.debug("role_not_configured", role=role.value, error=str(exc))
        except Exception as exc:
            log.error(
                "role_map_inspection_failed",
                role=role.value,
                error=f"{type(exc).__name__}: {exc}",
            )
            return RoleMapModels(
                inspected=False,
                detail=(f"inspecting role {role.value!r} raised {type(exc).__name__}: {exc}"),
            )

    return RoleMapModels(models=frozenset(model for model in found if model.strip()))


async def _run(args: argparse.Namespace, *, target: EvalTarget | None = None) -> int:
    """One run, start to exit code.

    ``target`` is injectable so the exit-code paths can be tested against a
    deterministic stub rather than by taking a model server away — which is not
    a thing an automated test may depend on, and is how E9 was found rather than
    how it should be reproduced.
    """
    if args.check_judge:
        return await _check_judge(args.role_map)
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

    # One client, built once, used twice: it runs the agent and it names the
    # models the judge is checked against. Skipped entirely when no agent will
    # run, so `--no-agent` still needs no role map and no provider config.
    llm = None
    if not (args.no_agent or agent is None or target is not None):
        try:
            llm = _build_client(args.role_map)
        except Exception as exc:
            # No case can run without it, so this is not a gate failure — it is
            # a run that never started. Reported like one rather than as a
            # traceback ([ADR-0036]'s exit 3, [ADR-0037] §1).
            print(
                f"Role map {args.role_map!r} could not be loaded: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return EXIT_UNMEASURED
    if target is None:
        target = _build_target(agent, llm, args.no_agent)

    # The judge learns what it is being asked to grade. `judge_from_env()` stays
    # ignorant of the role map — it is told, afterwards, and only ever downgraded
    # ([ADR-0037], open question E11).
    judge = (
        None
        if args.no_judge
        else Judge(resolve_judge_trust(judge_from_env(), _models_in_play(llm)))
    )

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
