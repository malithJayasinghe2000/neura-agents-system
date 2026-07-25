#!/usr/bin/env python3
"""The most important check in this repository.

No commerce-platform name may appear in code outside `packages/neura-adapters/`.
If one does, the core has learned about a specific platform — and the
platform-independence claim the entire product is built on is no longer true
(docs/architecture/adr/0003-canonical-domain-model.md).

This is a blocking CI check, not a guideline. Boundaries that are not
mechanically enforced erode within weeks.

**Comments and docstrings are excluded.** The rule protects against
platform-specific *behaviour*, and prose cannot contain behaviour — a docstring
saying "this must not know Shopify exists" is the rule being documented, not
broken. Scanning executable code only keeps the check precise instead of merely
loud, and lets the code explain its own constraints.

    uv run python scripts/check_platform_independence.py
"""

from __future__ import annotations

import io
import re
import sys
import token as token_mod
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PLATFORM_NAMES = (
    "bagisto",
    "shopify",
    "woocommerce",
    "magento",
    "bigcommerce",
    "prestashop",
    "opencart",
    "commercetools",
)

# Where a platform name is legitimate anywhere, prose or code.
ALLOWED_PREFIXES = (
    "packages/neura-adapters/",
    "docs/",
    "scripts/check_platform_independence.py",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
)

SEARCH_ROOTS = ("packages", "apps", "agents", "evals", "tests", "infra", "scripts")
SEARCH_SUFFIXES = {".py", ".sql", ".toml", ".yml", ".yaml", ".json", ".js", ".ts"}

_PATTERN = re.compile("|".join(re.escape(n) for n in PLATFORM_NAMES), re.IGNORECASE)

Violation = tuple[str, int, str]


def _is_allowed(rel_path: str) -> bool:
    return any(rel_path.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _python_code_lines(source: str) -> dict[int, str]:
    """Line number -> code content, with comments and string literals removed.

    String literals go too: docstrings are strings, and a platform name inside a
    runtime string would be data rather than a structural dependency. Real
    coupling shows up as an identifier, import or key — which survives here.
    """
    code_by_line: dict[int, str] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type in (token_mod.COMMENT, token_mod.STRING, token_mod.NL, token_mod.NEWLINE):
                continue
            line = tok.start[0]
            code_by_line[line] = code_by_line.get(line, "") + " " + tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file — fall back to scanning everything rather than skipping.
        return dict(enumerate(source.splitlines(), start=1))
    return code_by_line


def _plain_code_lines(source: str) -> dict[int, str]:
    """For non-Python files: drop whole-line and trailing ``#``/``--`` comments."""
    result: dict[int, str] = {}
    for lineno, line in enumerate(source.splitlines(), start=1):
        code = re.split(r"#|--", line, maxsplit=1)[0]
        if code.strip():
            result[lineno] = code
    return result


def scan() -> list[Violation]:
    violations: list[Violation] = []

    for root in SEARCH_ROOTS:
        root_path = REPO_ROOT / root
        if not root_path.exists():
            continue

        for path in sorted(root_path.rglob("*")):
            if not path.is_file() or path.suffix not in SEARCH_SUFFIXES:
                continue

            rel = path.relative_to(REPO_ROOT).as_posix()
            if _is_allowed(rel):
                continue

            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            lines = (
                _python_code_lines(source) if path.suffix == ".py" else _plain_code_lines(source)
            )
            for lineno, code in sorted(lines.items()):
                if _PATTERN.search(code):
                    violations.append((rel, lineno, code.strip()))

    return violations


def main() -> int:
    violations = scan()

    if not violations:
        print("✔ platform independence: no platform names in code outside adapters/")
        return 0

    print("✘ PLATFORM INDEPENDENCE VIOLATED\n", file=sys.stderr)
    print(
        "A commerce-platform name appears in code outside packages/neura-adapters/.\n"
        "The core must not know which platforms exist.\n\n"
        "Needed platform-specific behaviour? You don't — declare a Capability and\n"
        "let the adapter satisfy it. See docs/architecture/commerce-integration.md §3.\n",
        file=sys.stderr,
    )
    for rel, lineno, text in violations:
        print(f"  {rel}:{lineno}: {text}", file=sys.stderr)
    print(f"\n{len(violations)} violation(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
