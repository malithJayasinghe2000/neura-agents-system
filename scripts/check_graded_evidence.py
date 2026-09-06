#!/usr/bin/env python3
"""What every captured replay artefact must be — [ADR-0035].

`check_platform_independence.py` stops scanning these files for platform names,
because a merchant's own catalogue text and storefront URLs are their data and
not our behaviour. **This is the check that makes that exemption defensible.**

An exemption with nothing behind it is the erosion the other module's docstring
warns about, so the trade is explicit: those files stop being checked
*textually* and start being checked *structurally*, which is strictly harder to
satisfy. A platform name may appear inside a merchant's policy text; a
`platform` **field**, a `raw` payload, a credential or a customer's order may
not appear at all.

    uv run python scripts/check_graded_evidence.py

Run by `make arch`, beside the platform check, because the two are one decision.

## What it does not do

It does not look at *values* for platform names — that is the whole point of
ADR-0035. It looks at **shape**: which keys exist, whether the three hashes
agree, whether the schema is one this code can replay. Shape is where
platform-specific behaviour would have to live, and shape is what a generated
file can be held to exactly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages/neura-agent-core/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# The exemption's one definition, imported rather than restated. It was stated
# twice — an `fnmatch` glob here, `Path.glob` there — and the two dialects
# disagree about whether `*` crosses `/`, so the exemption silently covered more
# paths than this check did. That is the one relationship between them that must
# never hold, so there is now exactly one function.
from check_platform_independence import is_graded_evidence  # noqa: E402

from neura_agent_core.evidence import (  # noqa: E402
    PLATFORM_PAYLOAD_FIELDS,
    PROVENANCE_FIELDS,
    REPLAY_KEYS,
    SCHEMA_VERSION,
    contains_credential,
    content_hash_of,
)

#: Where to look. The *shape* test is `is_graded_evidence`; this only bounds the
#: walk so it does not cross the whole repository.
SEARCH_ROOT = "agents"


def artefacts() -> list[Path]:
    """Every file the platform checker exempts, and therefore every file this
    must check. Selected by the imported predicate, so the two sets are the same
    set by construction rather than by two authors agreeing."""
    root = REPO_ROOT / SEARCH_ROOT
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*.json")
        if is_graded_evidence(path.relative_to(REPO_ROOT).as_posix())
    )


#: Keys a merchant's own entity may carry into the repository. Anything else is
#: refused rather than ignored — an allowlist, because the failure direction
#: that matters is a field nobody thought about being written to git.
ALLOWED_TOP_LEVEL = {
    "_note",
    "_content_hash",
    "_captured_at",
    *REPLAY_KEYS,
}

#: Never in an exported artefact. `tenant_id`, `neura_id`, `platform` and
#: `synced_at` are provenance this side assigns and never accepts from a file;
#: `raw` is the commerce platform's own payload, whose *field names* would be
#: real platform coupling rather than merchant prose; `store_id` is internal
#: scoping that ADR-0034 §7 keeps out of every export.
FORBIDDEN_ANYWHERE = frozenset({*PROVENANCE_FIELDS, *PLATFORM_PAYLOAD_FIELDS, "store_id"})

Problem = tuple[str, str]


def _keys_anywhere(node: Any) -> set[str]:
    """Every mapping key in a nested structure, at any depth.

    Recursive because `raw` and `neura_id` live *inside* entities and recorded
    call results, not at the top level — a top-level-only check would pass a
    file carrying a platform's field names in every product.
    """
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            found |= _keys_anywhere(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys_anywhere(item)
    return found


def check_artefact(path: Path, payload: dict[str, Any]) -> list[Problem]:
    """Everything one artefact must satisfy. Collected, not raised one at a time."""
    problems: list[Problem] = []
    name = path.name

    # ── Schema ───────────────────────────────────────────────────────────────
    version = payload.get("schema_version")
    if not isinstance(version, int):
        problems.append((name, "no integer `schema_version` — this cannot be replayed"))
    elif version > SCHEMA_VERSION:
        problems.append(
            (name, f"schema {version} is newer than this code understands ({SCHEMA_VERSION})")
        )
    elif version < 2:
        problems.append(
            (
                name,
                f"schema {version} predates the `pii_output` flag, so it cannot say whether a "
                "tool returning customer data ran",
            )
        )

    # ── The three hashes ─────────────────────────────────────────────────────
    embedded = str(payload.get("_content_hash", ""))
    recomputed = content_hash_of({k: payload[k] for k in REPLAY_KEYS if k in payload})
    if not embedded:
        problems.append((name, "no `_content_hash` — the artefact is not content-addressed"))
    elif path.stem != embedded:
        problems.append(
            (name, f"filename does not match its embedded hash {embedded[:16]}… — renamed by hand?")
        )
    elif recomputed != embedded:
        problems.append(
            (
                name,
                f"content hashes to {recomputed[:16]}… but declares {embedded[:16]}… — modified "
                "since it was written",
            )
        )

    # ── Shape ────────────────────────────────────────────────────────────────
    if unexpected := sorted(set(payload) - ALLOWED_TOP_LEVEL):
        problems.append((name, f"unexpected top-level key(s) {unexpected}"))

    if forbidden := sorted(_keys_anywhere(payload) & FORBIDDEN_ANYWHERE):
        problems.append(
            (
                name,
                f"forbidden field(s) {forbidden} — provenance, platform payload and internal "
                "ids are assigned by this side and never written to a file",
            )
        )

    # ── Contents that must never reach a repository ──────────────────────────
    if secret := contains_credential(payload):
        problems.append((name, f"credential-shaped value {secret!r}"))

    if payload.get("pii_output") is not False:
        problems.append(
            (
                name,
                "`pii_output` is not False — a turn that ran a tool returning customer data "
                "must never have been exported",
            )
        )

    return problems


def scan() -> list[Problem]:
    problems: list[Problem] = []
    for path in artefacts():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append((path.name, f"unreadable: {exc}"))
            continue
        if not isinstance(payload, dict):
            problems.append((path.name, "not a JSON object"))
            continue
        problems.extend(check_artefact(path, payload))
    return problems


def main() -> int:
    problems = scan()
    count = len(artefacts())

    if not problems:
        print(f"✔ graded evidence: {count} artefact(s) structurally sound")
        return 0

    print("\n✘ GRADED EVIDENCE IS NOT WHAT IT MUST BE\n")
    print("These files are exempt from the platform-name scan (ADR-0035) precisely")
    print("because they are held to this instead. Fix or delete them.\n")
    for name, problem in problems:
        print(f"  {name}\n      {problem}\n")
    print(f"{len(problems)} problem(s).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
