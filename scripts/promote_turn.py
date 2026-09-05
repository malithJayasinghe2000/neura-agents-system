#!/usr/bin/env python3
"""A graded shadow turn becomes an eval case. ADR-0032.

    make promote-list TENANT=tn_...
    make promote TENANT=tn_... TURN=msg_... FACTS="30 days|full refund"

**This is the step that was promised in three places and built in none** — the
console's Review screen said verdicts "become the examples it is tested
against", `agent-runtime.md` §6 and `evaluation-strategy.md` §2 said the same,
and no code under any ``evals/`` directory had ever read ``shadow_turns``.

## Why a command and not a button

ADR-0032 §9 puts promoted cases in the repository: editing one is a commit and
deleting one is a commit, so that no assertion can change without a diff and a
name against it. **A console served from a host that has no working tree cannot
honour that.** So the console keeps grading — which is the merchant's judgement
and belongs to them — and promotion, which writes a file that can block a merge,
is run by somebody holding the repository. A console flow can feed this later
without changing what it writes.

## What it refuses, and why each refusal exists

Every one of these is a rule ADR-0032 argues for, enforced here rather than
described:

* **An ungraded turn.** There is no judgement to promote.
* **A ``disagree``.** §5. It records that a reply was wrong and not what right
  would have been, and a test needs the second.
* **A turn already promoted.** §10. A duplicate is not a spare row — the same
  question would be counted twice in every rate the suite reports.
* **A fact that is not in the draft, verbatim.** §11. Free text lets a human
  assert something the agent never said, wearing the authority of
  ``synthetic: false``.
* **``must_contain`` on an escalated turn.** Not in the ADR, and learned from
  A14: ``recommend_004`` failed only because escalation replaced the draft with
  the handover message, so an assertion on the draft's words was unsatisfiable
  before the model saw it. An escalated turn asserts that it escalated.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from neura_agent_core.conversations import conversation_messages
from neura_agent_core.shadow import ShadowRepository, ShadowTurn, ShadowVerdict
from neura_core import Database, load_env

#: Where a promoted case lands, per agent. The file is discovered by
#: ``load_all()``'s ``*.yaml`` glob, so it needs no registration.
GRADED_DATASET = "graded.yaml"

#: ``tags`` entries that carry provenance (ADR-0032 §6). Prefixes rather than
#: bare values so a reader of the YAML can tell what each one is.
FROM_TURN = "from-turn:"
PROMOTED_BY = "promoted-by:"

REPO = Path(__file__).resolve().parents[1]

AGENT_DATASETS = {
    "care": REPO / "agents/care/src/neura_agent_care/evals/datasets",
    "sell": REPO / "agents/sell/src/neura_agent_sell/evals/datasets",
}

HEADER = """\
Cases promoted from graded shadow turns — ADR-0032.

EVERY CASE HERE IS REAL. `synthetic: false` is the whole point of this file:
each one is a question a person actually asked, answered by the agent, withheld
by shadow mode, and graded by a human who then chose which facts must survive.

DO NOT hand-write a case into this file. It is written by
`make promote TURN=... FACTS="..."`, which refuses a fact that is not in the
approved draft verbatim, refuses a turn that was already promoted, and refuses
a `disagree`. A hand-written case here would claim an authority it has not got.

To remove a case, delete it and say why in the commit message. There is
deliberately no disable flag (ADR-0032 §9): a switch that silences a failing
case is how a suite rots.
"""


class _Dumper(yaml.SafeDumper):
    """Multi-line strings as literal blocks.

    The default folds them into one quoted scalar with blank lines wedged in,
    which turns this file's header — the part telling a reader not to hand-write
    a case here — into something nobody will read.
    """


def _literal(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _literal)


def _render(dataset: dict[str, Any]) -> str:
    return yaml.dump(dataset, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=88)


def _dataset_path(agent_key: str) -> Path:
    directory = AGENT_DATASETS.get(agent_key)
    if directory is None:
        raise SystemExit(f"no dataset directory known for agent {agent_key!r}")
    return directory / GRADED_DATASET


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"name": "graded", "description": HEADER, "cases": []}
    loaded = yaml.safe_load(path.read_text()) or {}
    loaded.setdefault("cases", [])
    return loaded


def _already_promoted(cases: list[dict[str, Any]], turn_id: str) -> str | None:
    for case in cases:
        for tag in case.get("tags") or []:
            if tag == f"{FROM_TURN}{turn_id}":
                return str(case.get("id"))
    return None


def build_case(
    turn: ShadowTurn, shopper_message: str, facts: list[str], *, case_id: str
) -> dict[str, Any]:
    """One ``EvalCase``, as a plain dict ready to be written.

    Everything except the facts is read off the turn. That is the point of
    ADR-0032: a graded turn already carries `input`, `intent`, `tools`,
    `grounded` and `escalated`, and the only thing a human has to supply is
    which words must survive a rewording.
    """
    expect: dict[str, Any] = {"intent": turn.intent, "escalated": turn.escalated}
    if turn.grounded is not None:
        expect["grounded"] = turn.grounded
    if turn.tools:
        expect["tools_called"] = sorted(turn.tools)

    if facts:
        # A harmful reply is promoted so that it never comes back; an approved
        # one so that what made it right survives. Same selection, opposite
        # assertion, and the verdict is what decides which (ADR-0032 §5).
        key = (
            "must_not_contain"
            if turn.verdict is ShadowVerdict.WOULD_HAVE_HARMED
            else "must_contain"
        )
        expect[key] = facts

    return {
        "id": case_id,
        "intent": turn.intent,
        "synthetic": False,
        "input": shopper_message,
        "expect": expect,
        "tags": [
            "graded",
            turn.agent_key,
            f"{FROM_TURN}{turn.id}",
            f"{PROMOTED_BY}{turn.reviewed_by or 'unknown'}",
        ],
        "notes": (
            f"Promoted from a verdict of `{turn.verdict.value if turn.verdict else '?'}` on "
            f"{turn.created_at.date().isoformat() if turn.created_at else 'an unknown date'}. "
            f"{turn.note or 'The reviewer left no note.'}"
        ),
    }


def check(turn: ShadowTurn, facts: list[str], existing: list[dict[str, Any]]) -> list[str]:
    """Every reason this promotion must not happen. Collected, not raised one
    at a time, so a caller fixing them sees all of them at once."""
    problems: list[str] = []

    if turn.verdict is None:
        problems.append("that turn has no verdict — grade it in the console first")
    elif turn.verdict is ShadowVerdict.DISAGREE:
        problems.append(
            "a `disagree` records that a reply was wrong, not what right would have "
            "been, and a test needs the second (ADR-0032 §5). Promote it only by "
            "writing the expectation by hand."
        )

    if (dupe := _already_promoted(existing, turn.id)) is not None:
        problems.append(
            f"that turn is already case `{dupe}` (ADR-0032 §10) — a duplicate would "
            "count the same question twice in every rate"
        )

    if facts and turn.escalated and turn.verdict is not ShadowVerdict.WOULD_HAVE_HARMED:
        problems.append(
            "an escalated turn replaced its draft with the handover message, so an "
            "assertion on the draft's words can never be satisfied (A14, "
            "`recommend_004`). Promote it with no facts — it asserts that it escalated."
        )

    for fact in facts:
        if fact not in turn.draft:
            problems.append(
                f"{fact!r} does not appear in the approved draft, verbatim "
                "(ADR-0032 §11). Only what the agent actually said may be asserted."
            )

    return problems


async def _shopper_message(session: Any, tenant_id: str, message_id: str) -> str:
    row = (
        await session.execute(
            select(conversation_messages.c.content)
            .where(conversation_messages.c.tenant_id == tenant_id)
            .where(conversation_messages.c.id == message_id)
        )
    ).first()
    return str(row[0]) if row else ""


async def promote(tenant_id: str, turn_id: str, facts: list[str], *, dry_run: bool) -> int:
    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant_id) as session:
            turn = await ShadowRepository(session).get(tenant_id, turn_id)
            if turn is None:
                print(f"  no shadow turn {turn_id} in {tenant_id}", file=sys.stderr)
                return 1
            shopper = await _shopper_message(session, tenant_id, turn.message_id)
    finally:
        await db.dispose()

    if not shopper:
        print("  the shopper's own message is not in the transcript", file=sys.stderr)
        return 1

    path = _dataset_path(turn.agent_key)
    dataset = _load(path)

    if problems := check(turn, facts, dataset["cases"]):
        print("\n  REFUSED:\n", file=sys.stderr)
        for problem in problems:
            print(f"    · {problem}\n", file=sys.stderr)
        return 1

    case_id = f"graded_{turn.agent_key}_{len(dataset['cases']) + 1:03d}"
    case = build_case(turn, shopper, facts, case_id=case_id)
    dataset["cases"].append(case)

    rendered = _render(dataset)
    if dry_run:
        print(rendered)
        return 0

    path.write_text(rendered)
    print(f"\n  ✔ {case_id} → {path.relative_to(REPO)}")
    print(f"    asked:    {shopper}")
    print(f"    verdict:  {turn.verdict.value if turn.verdict else '?'}")
    for key in ("must_contain", "must_not_contain"):
        if key in case["expect"]:
            print(f"    {key}: {case['expect'][key]}")
    print("\n  Not committed. Read the diff before you do — this case can block a merge.\n")
    return 0


async def listing(tenant_id: str) -> int:
    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant_id) as session:
            turns = await ShadowRepository(session).pending(tenant_id, graded=True, limit=200)
            messages = {
                t.id: await _shopper_message(session, tenant_id, t.message_id) for t in turns
            }
    finally:
        await db.dispose()

    if not turns:
        print(f"\n  no graded turns in {tenant_id}\n")
        return 0

    promoted: dict[str, str] = {}
    for agent_key in AGENT_DATASETS:
        for case in _load(_dataset_path(agent_key))["cases"]:
            for tag in case.get("tags") or []:
                if tag.startswith(FROM_TURN):
                    promoted[tag[len(FROM_TURN) :]] = str(case.get("id"))

    print(f"\n  {len(turns)} graded turn(s) in {tenant_id}\n")
    for turn in turns:
        verdict = turn.verdict.value if turn.verdict else "?"
        if turn.id in promoted:
            state = f"promoted → {promoted[turn.id]}"
        elif turn.verdict is ShadowVerdict.DISAGREE:
            state = "not promotable (disagree)"
        else:
            state = "READY"
        print(f"  {turn.id}  {turn.agent_key:5s} {verdict:18s} {state}")
        print(f"      asked: {messages.get(turn.id, '?')}")
        print(f"      draft: {turn.draft[:96].replace(chr(10), ' ')}…\n")
    print('  Promote:  make promote TENANT=… TURN=msg_… FACTS="a fact|another"\n')
    return 0


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="promote", description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--turn", help="shadow turn id; omit to list")
    parser.add_argument(
        "--facts",
        default="",
        help="pipe-separated spans of the draft that must survive. Each is checked "
        "against the draft verbatim and refused if absent.",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the file, write nothing")
    args = parser.parse_args()

    facts = [f.strip() for f in args.facts.split("|") if f.strip()]
    if args.turn:
        raise SystemExit(asyncio.run(promote(args.tenant, args.turn, facts, dry_run=args.dry_run)))
    raise SystemExit(asyncio.run(listing(args.tenant)))


if __name__ == "__main__":
    main()
