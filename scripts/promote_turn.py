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
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from neura_agent_core.conversations import conversation_messages
from neura_agent_core.evidence import (
    EvidenceBundle,
    EvidenceError,
    artefact_path,
    contains_credential,
    export_artefact,
    fingerprint,
)
from neura_agent_core.shadow import ShadowRepository, ShadowTurn, ShadowVerdict
from neura_agent_core.shadow_evidence import ShadowEvidenceRepository
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, load_env
from neura_core.tenancy.schema import tenant_stores

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

#: Where a promoted case's captured evidence lands, per agent. Content-addressed
#: under `graded/`, so two cases replaying the same shop share one file and no
#: file's meaning moves under a case citing it ([ADR-0034] §4).
AGENT_FIXTURES = {
    "care": REPO / "agents/care/src/neura_agent_care/evals/fixtures",
    "sell": REPO / "agents/sell/src/neura_agent_sell/evals/fixtures",
}

#: `synced_entities.entity_type` -> the bundle's fixture section. Staleness is
#: checked per entity, so the two vocabularies have to meet somewhere.
_ENTITY_SECTIONS = {"product": "products", "category": "categories", "policy": "policies"}

HEADER = """\
Cases promoted from graded shadow turns — ADR-0032.

EVERY CASE HERE IS REAL. `synthetic: false` is the whole point of this file:
each one is a question a person actually asked, answered by the agent, withheld
by shadow mode, and graded by a human who then chose which facts must survive.

EVERY CASE HERE REPLAYS ITS OWN EVIDENCE. `fixture_mode: replay` means the base
fixture store is NOT loaded: the case runs against the boundary its turn actually
recorded, under `fixtures/graded/<content hash>.json` (ADR-0034). That is what
makes it reproducible rather than merely real.

DO NOT hand-write a case into this file. It is written by
`make promote TURN=... FACTS="..."`, which refuses a fact that is not in the
approved draft verbatim, refuses a turn that was already promoted, refuses a
`disagree`, refuses a turn with no captured evidence, refuses one that touched
customer data, and refuses one whose store has changed since it was graded. A
hand-written case here would claim an authority it has not got.

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
    turn: ShadowTurn,
    shopper_message: str,
    facts: list[str],
    *,
    case_id: str,
    evidence_hash: str,
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
    # Always, including the empty list — which is an assertion, not an omission.
    #
    # A promoted case knows exactly which tools its turn ran, so "none" is a fact
    # it can state. Omitting it left the case unscored for tool selection and the
    # harness said so in as many words: *"the agent called no tools, and this
    # case does not say whether it should have… a turn that used none of the
    # store's data cannot be left unscored."* Measured on the first real promoted
    # case, which answered from retrieval alone and failed only this.
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
        # Explicit, never inferred from this file's name ([ADR-0034] §5). The
        # base fixture is NOT loaded for these: a promoted case runs against the
        # boundary its turn recorded and nothing else.
        "fixture_mode": "replay",
        "evidence": evidence_hash,
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


def evidence_problems(bundle: EvidenceBundle | None) -> list[str]:
    """Every reason this turn's evidence must not become a file — [ADR-0034] §8.

    Collected rather than raised one at a time, like `check`, so somebody fixing
    a promotion sees the whole picture at once.
    """
    problems: list[str] = []

    if bundle is None:
        problems.append(
            "no evidence was captured for that turn (ADR-0034 §1). Turns that ran "
            "before capture existed cannot be promoted, and there is deliberately no "
            "way to reconstruct what they saw: rebuilding a store from today's synced "
            "rows asserts a human's approval against data that human never saw."
        )
        return problems

    if bundle.is_empty:
        problems.append(
            "the captured evidence records no successful store call and no retrieval, "
            "so a replay would answer every question with nothing — indistinguishable "
            "from a shop that stocks nothing (ADR-0034 §6)."
        )

    if bundle.schema_version < 2:
        problems.append(
            f"the evidence was captured under schema {bundle.schema_version}, which "
            "predates the `pii_output` flag and cannot say whether a tool returning "
            "customer data ran. Refusing rather than assuming it did not."
        )
    elif bundle.pii_output:
        problems.append(
            "a tool declaring `pii_output` ran on this turn, so it returned customer "
            "data. A promoted case is a file in this repository and a shopper's order "
            "may not be (ADR-0034 §8). Order-status turns cannot be promoted."
        )

    if secret := contains_credential(bundle.model_dump(mode="json")):
        problems.append(
            f"the captured evidence contains a credential-shaped value ({secret!r}). "
            "Refusing rather than filtering: a filter would leave nobody knowing one "
            "had been captured."
        )

    return problems


async def store_scope(session: Any, tenant_id: str, store_id: str) -> tuple[str | None, str | None]:
    """Which platform's synced rows belong to this evidence — or why nobody knows.

    Returns ``(platform, refusal)``; exactly one is ever set.

    **The architecture gap this exists to refuse around.** ``synced_entities`` is
    keyed ``(tenant_id, platform, entity_type, external_id)`` and has **no
    ``store_id`` column**, while ``tenant_stores`` has always permitted several
    stores per tenant — its own comment says *"two shops on the same software is
    the ordinary case rather than the exotic one"*. So two stores on the same
    platform write to the same synced rows, and **which store a product came
    from is not recoverable**.

    Scoping by ``platform`` is real data read from ``tenant_stores``, not an
    invented mapping — it is exact whenever a tenant's stores are on different
    platforms, and it is exactly the case above that it cannot answer.

    **Every unclear case refuses**, because the alternative is a staleness check
    that silently compares against the wrong shop and reports "unchanged". A
    check that can be wrong in the reassuring direction is worse than no check.
    Recorded as open question **C5**.
    """
    rows = (
        await session.execute(
            select(tenant_stores.c.id, tenant_stores.c.platform).where(
                tenant_stores.c.tenant_id == tenant_id
            )
        )
    ).all()

    if not rows:
        return None, (
            "this tenant has no connected store, so there is nothing to compare the "
            "captured evidence against and no way to tell whether the shop has moved."
        )

    platform_of = {str(row.id): str(row.platform) for row in rows}

    if store_id not in platform_of:
        return None, (
            f"the evidence was captured against store {store_id!r}, which is no longer "
            "connected to this tenant. Whether that shop has changed is unknowable."
        )

    platform = platform_of[store_id]
    siblings = sorted(i for i, p in platform_of.items() if p == platform and i != store_id)
    if siblings:
        return None, (
            f"this tenant has {len(siblings) + 1} stores on the same platform "
            f"({store_id!r} and {', '.join(repr(s) for s in siblings)}), and "
            "`synced_entities` has no store_id column — so the synced copy cannot say "
            "which shop a product came from. Refusing rather than checking staleness "
            "against possibly the wrong shop (open question C5)."
        )

    return platform, None


async def stale_entities(
    session: Any, tenant_id: str, bundle: EvidenceBundle
) -> tuple[list[str], str | None]:
    """Which captured entities the shop has changed since — [ADR-0034] §9.

    Returns ``(moved, refusal)``. A refusal means staleness could not be checked
    at all (see :func:`store_scope`), which is itself a reason not to promote.

    Compares each captured fingerprint against the synced copy **for this
    evidence's own store**, so a tenant's second shop cannot answer for the
    first. A moved entity refuses promotion **before** it can fail later for a
    reason that looks exactly like a regression, which is ADR-0032 §12's
    *"better answer, recorded and not built"*.

    An entity absent from ``synced_entities`` is skipped and does **not** refuse:
    absence means the sync has never seen it, so there is nothing to compare, and
    treating "unknown" as "changed" would block promotion on a sync that had not
    run yet.
    """
    platform, refusal = await store_scope(session, tenant_id, bundle.store_id)
    if refusal is not None:
        return [], refusal

    rows = (
        await session.execute(
            select(
                synced_entities.c.entity_type,
                synced_entities.c.external_id,
                synced_entities.c.document,
            )
            .where(synced_entities.c.tenant_id == tenant_id)
            .where(synced_entities.c.platform == platform)
        )
    ).all()

    current = {
        f"{_ENTITY_SECTIONS[row.entity_type]}:{row.external_id}": row.document
        for row in rows
        if row.entity_type in _ENTITY_SECTIONS
    }

    moved: list[str] = []
    for key, captured in sorted(bundle.source_fingerprints.items()):
        document = current.get(key)
        if document is None:
            continue
        if fingerprint(document) != captured:
            moved.append(key)
    return moved, None


def write_artefact(agent_key: str, bundle: EvidenceBundle) -> str:
    """The captured boundary, as a content-addressed file. Returns its hash.

    **Atomic and collision-safe.** Written to a temporary file in the same
    directory and moved into place, so a crash halfway leaves either the old file
    or the new one and never half of either. An artefact that already exists is
    left alone rather than rewritten: it is content-addressed, so an existing
    file with this name already holds exactly these bytes, and rewriting it would
    be a write that could only ever do harm.
    """
    payload = export_artefact(bundle)
    content_hash = str(payload["_content_hash"])
    path = artefact_path(AGENT_FIXTURES[agent_key], content_hash)
    if path.exists():
        return content_hash

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=False) + "\n")
    return content_hash


def _atomic_write(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def next_case_id(agent_key: str, cases: list[dict[str, Any]]) -> str:
    """The first unused id for this agent.

    Counting the cases would collide the moment one is deleted — and ADR-0032 §9
    says deletion is the *only* way to remove a case, so that is the ordinary
    path rather than the exotic one.
    """
    taken = {str(case.get("id")) for case in cases}
    index = 1
    while (case_id := f"graded_{agent_key}_{index:03d}") in taken:
        index += 1
    return case_id


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
            # What the turn actually saw. Captured while it ran or not at all —
            # there is no reconstruction path, by design ([ADR-0034] §1).
            bundle = await ShadowEvidenceRepository(session).get(tenant_id, turn_id)
            moved, scope_refusal = (
                await stale_entities(session, tenant_id, bundle) if bundle else ([], None)
            )
    finally:
        await db.dispose()

    if not shopper:
        print("  the shopper's own message is not in the transcript", file=sys.stderr)
        return 1

    path = _dataset_path(turn.agent_key)
    dataset = _load(path)

    problems = check(turn, facts, dataset["cases"]) + evidence_problems(bundle)
    if scope_refusal:
        problems.append(f"staleness could not be checked: {scope_refusal}")
    if moved:
        problems.append(
            "the store has changed since this turn was graded — "
            + ", ".join(moved)
            + ". Promoting now would assert a human's approval against data that "
            "human never saw (ADR-0034 §9). Grade a fresh turn instead."
        )
    if problems:
        print("\n  REFUSED:\n", file=sys.stderr)
        for problem in problems:
            print(f"    · {problem}\n", file=sys.stderr)
        return 1

    if bundle is None:  # pragma: no cover - `evidence_problems` refuses this above
        return 1
    try:
        evidence_hash = write_artefact(turn.agent_key, bundle)
    except EvidenceError as exc:
        print(f"\n  REFUSED:\n\n    · {exc}\n", file=sys.stderr)
        return 1

    case_id = next_case_id(turn.agent_key, dataset["cases"])
    case = build_case(turn, shopper, facts, case_id=case_id, evidence_hash=evidence_hash)
    dataset["cases"].append(case)

    rendered = _render(dataset)
    if dry_run:
        print(rendered)
        return 0

    _atomic_write(path, rendered)
    print(f"\n  ✔ {case_id} → {path.relative_to(REPO)}")
    print(
        f"    evidence: {artefact_path(AGENT_FIXTURES[turn.agent_key], evidence_hash).relative_to(REPO)}"
    )
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
            # Whether each turn can be replayed at all. Shown in the listing
            # rather than discovered at promotion time, because "this one has no
            # evidence" is the commonest answer for anything graded before
            # 2026-09-06 and it should not take a failed command to learn it.
            evidence_repo = ShadowEvidenceRepository(session)
            bundles = {t.id: await evidence_repo.get(tenant_id, t.id) for t in turns}
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
        elif problems := evidence_problems(bundles.get(turn.id)):
            state = f"not promotable ({len(problems)} evidence problem(s))"
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
