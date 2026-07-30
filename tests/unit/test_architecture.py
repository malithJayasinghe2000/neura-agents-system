"""Tests that the architecture is real rather than aspirational.

Documented rules are worthless unless something fails when they are broken.
These correspond to docs/architecture/overview.md §8.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    """Import the standalone check script as a module."""
    path = REPO_ROOT / "scripts/check_platform_independence.py"
    spec = importlib.util.spec_from_file_location("_platform_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_platform_independence() -> None:
    """No commerce-platform name outside adapters/ and docs/.

    The most important check in the repository — it is what keeps the
    platform-independence claim true.
    """
    result = subprocess.run(
        [sys.executable, "scripts/check_platform_independence.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


class TestTheCheckerItself:
    """A check that cannot fail is worse than no check — it manufactures confidence.

    These prove the detector actually detects, and that its comment/docstring
    exemption is not a loophole wide enough to drive real coupling through.
    """

    def test_detects_a_platform_name_in_code(self) -> None:
        checker = _load_checker()
        source = "from vendor.shopify_sdk import Client\n"
        lines = checker._python_code_lines(source)
        assert any(checker._PATTERN.search(code) for code in lines.values())

    def test_ignores_a_platform_name_in_a_comment(self) -> None:
        checker = _load_checker()
        source = "# this must never import Shopify\nvalue = 1\n"
        lines = checker._python_code_lines(source)
        assert not any(checker._PATTERN.search(code) for code in lines.values())

    def test_ignores_a_platform_name_in_a_docstring(self) -> None:
        checker = _load_checker()
        source = '"""Must not know Shopify exists."""\nvalue = 1\n'
        lines = checker._python_code_lines(source)
        assert not any(checker._PATTERN.search(code) for code in lines.values())

    def test_still_detects_code_on_a_line_with_a_comment(self) -> None:
        """The exemption must not swallow the code preceding a comment."""
        checker = _load_checker()
        source = "import shopify_client  # unavoidable, sorry\n"
        lines = checker._python_code_lines(source)
        assert any(checker._PATTERN.search(code) for code in lines.values())

    def test_unparseable_python_falls_back_to_scanning_everything(self) -> None:
        """A syntax error must not become a silent way to bypass the check."""
        checker = _load_checker()
        lines = checker._python_code_lines("def broken( :\n  import shopify\n")
        assert any(checker._PATTERN.search(code) for code in lines.values())


def test_domain_is_pure() -> None:
    """neura_domain must import nothing but Pydantic and the stdlib.

    Purity is what allows every other layer to be swapped. A single database or
    HTTP import here would quietly couple the vocabulary to an implementation.
    """
    forbidden = {
        "neura_core",
        "neura_llm",
        "neura_commerce",
        "neura_adapters",
        "neura_agent_core",
        "neura_api",
        "sqlalchemy",
        "httpx",
        "redis",
        "fastapi",
        "asyncpg",
        "openai",
    }
    domain_src = REPO_ROOT / "packages/neura-domain/src/neura_domain"
    offenders: list[str] = []

    for path in domain_src.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            for module in forbidden:
                if f"import {module}" in stripped or stripped.startswith(f"from {module}"):
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{lineno}: {stripped}")

    assert not offenders, "neura_domain is not pure:\n" + "\n".join(offenders)


def test_agent_core_does_not_know_any_agent() -> None:
    """The engine must never learn an agent's name."""
    core_src = REPO_ROOT / "packages/neura-agent-core/src/neura_agent_core"
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for path in core_src.rglob("*.py")
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if line.strip().startswith(("import ", "from ")) and "neura_agent_care" in line
    ]
    assert not offenders, "neura_agent_core imports an agent:\n" + "\n".join(offenders)


def test_the_engine_imports_cleanly_from_either_direction() -> None:
    """A circular import that only fires in one import order is not a bug you
    find by running the tests — it is a bug you find by running *different*
    tests.

    `neura_agent_core.audit` reads the `audit_log` table out of `graph.schema`,
    which pulls in `graph/__init__`. Milestone 1.12 gave `graph.state` a reason
    to know about `AuditSink` and closed the loop. The unit suite happened to
    import `audit` late and stayed green; the integration suite imported it
    first and could not collect a single test.

    Two subprocesses, because the check is meaningless inside a process that has
    already imported both.
    """
    for first, second in (
        ("neura_agent_core.audit", "neura_agent_core.graph"),
        ("neura_agent_core.graph", "neura_agent_core.audit"),
    ):
        result = subprocess.run(  # noqa: S603 — two literals from the tuple above
            [sys.executable, "-c", f"import {first}; import {second}"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, f"importing {first} before {second} fails:\n{result.stderr}"


def test_commerce_does_not_know_any_adapter() -> None:
    """The adapter contract must not know which platforms implement it."""
    commerce_src = REPO_ROOT / "packages/neura-commerce/src/neura_commerce"
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for path in commerce_src.rglob("*.py")
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if line.strip().startswith(("import ", "from ")) and "neura_adapters" in line
    ]
    assert not offenders, "neura_commerce imports an adapter:\n" + "\n".join(offenders)
