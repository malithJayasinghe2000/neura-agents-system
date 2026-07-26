#!/usr/bin/env python3
"""Regenerate the published OpenAPI document.

    uv run python scripts/generate_spec.py     # or: make spec

The document is generated from the canonical Pydantic models, never edited by
hand. ``tests/unit/test_generic_adapter.py`` fails if the committed file and the
models disagree — a published contract that quietly drifts from the code is
worse than no published contract, because a merchant's developer implements the
stale version and only finds out in production.
"""

from __future__ import annotations

import sys
from pathlib import Path

from neura_adapters.generic.spec import render

SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "spec" / "openapi.json"


def main() -> int:
    document = render()
    changed = not SPEC_PATH.exists() or SPEC_PATH.read_text(encoding="utf-8") != document

    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(document, encoding="utf-8")

    rel = SPEC_PATH.relative_to(Path.cwd()) if SPEC_PATH.is_relative_to(Path.cwd()) else SPEC_PATH
    print(f"{'updated' if changed else 'unchanged'}: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
