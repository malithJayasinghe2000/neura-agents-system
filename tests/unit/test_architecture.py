"""Tests that the architecture is real rather than aspirational.

Documented rules are worthless unless something fails when they are broken.
These correspond to docs/architecture/overview.md §8.
"""

from __future__ import annotations

import importlib.util
import re
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


#: Any agent package, not one of them by name.
#:
#: This pattern used to be the literal string ``neura_agent_care``, which was
#: correct while CARE was the only agent and became a hole the moment SELL
#: existed — a check that names what it forbids stops working when somebody adds
#: the thing it did not know about. `neura_agent_core` itself is excluded, since
#: that is the engine rather than an agent.
_AGENT_IMPORT = re.compile(r"\bneura_agent_(?!core\b)[a-z_]+")


def test_agent_core_does_not_know_any_agent() -> None:
    """The engine must never learn an agent's name — any agent's."""
    core_src = REPO_ROOT / "packages/neura-agent-core/src/neura_agent_core"
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}  {line.strip()}"
        for path in core_src.rglob("*.py")
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if line.strip().startswith(("import ", "from ")) and _AGENT_IMPORT.search(line)
    ]
    assert not offenders, "neura_agent_core imports an agent:\n" + "\n".join(offenders)


def test_no_agent_imports_another_agent() -> None:
    """A hard rule in AGENTS.md, and now there are two agents to break it with.

    Cross-agent communication goes through the event bus (Phase 3), never a
    direct import. The duplication this forces — SELL's catalogue tools will be
    near-copies of CARE's — is deliberate and recorded as open question A12.
    """
    offenders = []
    for agent_src in sorted((REPO_ROOT / "agents").glob("*/src/neura_agent_*")):
        own = agent_src.name
        for path in agent_src.rglob("*.py"):
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if not line.strip().startswith(("import ", "from ")):
                    continue
                for found in _AGENT_IMPORT.findall(line):
                    if found != own:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}  {line.strip()}")
    assert not offenders, "an agent imports another agent:\n" + "\n".join(offenders)


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


class TestCiRunsWhatTheMakefileRuns:
    """CI and `make check` must not drift, because only one of them is run
    before a push and the other is the one that goes red.

    This is not hypothetical. On 2026-08-15 the workflow's typecheck line read
    ``mypy packages apps agents`` while the Makefile's read
    ``mypy packages apps agents evals``. Dropping ``evals`` hides
    ``neura_evals``' own type information, so the *agent* that imports it
    reported two ``import-untyped`` errors — a red CI caused entirely by the
    paths being checked, with nothing wrong in the code and nothing reproducible
    locally. It went unnoticed for six pushes because nobody on this machine can
    read the CI result (the repository is private and there is no `gh` here).
    """

    WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
    MAKEFILE = REPO_ROOT / "Makefile"

    def _mypy_paths(self, path: Path) -> set[str]:
        """The paths each file actually hands to mypy.

        Only real invocations — ``uv run mypy …`` — and only the part before a
        trailing comment, so the Makefile's own `## help text` and `.mypy_cache`
        in the clean target are not mistaken for arguments.
        """
        found: set[str] = set()
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("#") or "uv run mypy" not in line:
                continue
            _, _, tail = line.partition("uv run mypy")
            found |= {word for word in tail.split("#")[0].split() if not word.startswith("-")}
        return found

    def test_the_typechecked_paths_agree(self) -> None:
        ci = self._mypy_paths(self.WORKFLOW)
        makefile = self._mypy_paths(self.MAKEFILE)
        assert ci, "no `uv run mypy` invocation found in the workflow"
        assert ci == makefile, (
            f"CI typechecks {sorted(ci)} and `make typecheck` checks "
            f"{sorted(makefile)}. Whichever is smaller is the one that will "
            "surprise somebody."
        )

    def test_ci_connects_as_the_unprivileged_role(self) -> None:
        """PostgreSQL exempts superusers from every RLS policy, so a CI that
        connects as the owner runs the whole isolation suite against policies
        that are never consulted.

        ``Database.ping`` refuses to start on such a role, which is why this was
        a loud CI error rather than a silent green — but the refusal only helps
        the run it stops. This pins the configuration itself.
        """
        text = self.WORKFLOW.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "DATABASE_URL:" not in stripped:
                continue
            assert "neura_app:" in stripped, (
                f"CI sets an application DATABASE_URL to a privileged role: {stripped!r}. "
                "Row-Level Security does not apply to superusers, so the isolation "
                "tests would pass without testing anything (ADR-0008)."
            )

    def test_ci_runs_the_same_init_script_the_dev_stack_mounts(self) -> None:
        """A GitHub service container cannot mount a file, so the init script
        has to be run as a step — and it must be *this* file rather than a copy.

        Two scripts that are supposed to agree eventually will not, and the way
        that failure surfaces is CI proving tenant isolation against a database
        that never had the roles or the extensions.
        """
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        script = "infra/docker/init-db.sql"
        assert script in workflow, f"CI never runs {script}, so `neura_app` will not exist"
        assert script in compose, f"the dev stack no longer mounts {script}"

    def test_ci_migrates_before_it_tests(self) -> None:
        """Integration tests skip on an absent database and FAIL on an empty
        one, which is the right way round — but only if something has run the
        migrations first."""
        lines = self.WORKFLOW.read_text(encoding="utf-8").splitlines()
        migrate = next((i for i, x in enumerate(lines) if "alembic upgrade head" in x), -1)
        test = next((i for i, x in enumerate(lines) if "tests/integration" in x), -1)
        assert migrate != -1, "CI never runs migrations"
        assert test != -1, "CI never runs the integration tests"
        assert migrate < test, "CI runs the integration tests before migrating"


# The two checkers are scripts rather than packages — `make arch` runs them by
# path. Importing them here rather than shelling out keeps the assertions on
# specific rules instead of on an exit code.
sys.path.insert(0, str(REPO_ROOT / "scripts"))


class TestGradedEvidenceEarnsItsExemption:
    """[ADR-0035]. Captured evidence leaves the platform *text* scan and enters a
    structural one — and the exemption is only defensible while the second check
    is real and the first stays narrow.
    """

    def test_the_exemption_is_exactly_generated_graded_json(self) -> None:
        """Each `False` here is a way this could have been over-applied."""
        from check_platform_independence import _is_allowed

        assert _is_allowed("agents/care/src/neura_agent_care/evals/fixtures/graded/a.json")
        assert _is_allowed("agents/sell/src/neura_agent_sell/evals/fixtures/graded/deadbeef.json")

        for path in (
            "agents/care/src/neura_agent_care/evals/fixtures/store.json",
            "agents/care/src/neura_agent_care/evals/fixtures/graded/a.yaml",
            "agents/care/src/neura_agent_care/evals/datasets/graded.yaml",
            "agents/care/src/neura_agent_care/prompts/route.md",
            "agents/care/src/neura_agent_care/tools/catalogue.py",
            "packages/neura-agent-core/src/neura_agent_core/evidence.py",
            "apps/neura-api/some-config.json",
            "evals/fixtures/graded/a.json",
        ):
            assert not _is_allowed(path), f"{path} must still be scanned"

    def test_a_star_may_not_cross_a_directory_separator(self) -> None:
        """The bug this replaced, and it was invisible from either script alone.

        The exemption was an `fnmatch` glob, where **`*` matches `/`**; the
        structural check used `Path.glob`, where it does not. So every path below
        was exempted from the platform scan and checked by nothing — the
        exemption was strictly wider than the check that pays for it, which is
        the one relationship between them that must never hold.

        Both now call one segment-exact function.
        """
        from check_platform_independence import is_graded_evidence

        for path in (
            # an extra directory before `src`
            "agents/care/extra/src/neura_agent_care/evals/fixtures/graded/a.json",
            # a nested directory under `graded/`
            "agents/care/src/neura_agent_care/evals/fixtures/graded/nested/a.json",
            # an extra package level
            "agents/care/src/x/y/evals/fixtures/graded/a.json",
            # and traversal, for completeness
            "agents/care/src/neura_agent_care/evals/fixtures/graded/../../store.json",
        ):
            assert not is_graded_evidence(path), f"{path} slipped through the exemption"

    def test_the_exemption_and_the_structural_check_cover_one_set(self) -> None:
        """[ADR-0035] §3's whole argument, asserted rather than asserted-in-prose.

        Every file exempted from the platform-name scan must be a file the
        structural validator checks. Compared over the repository as it actually
        is, so a future artefact in an unexpected place fails here.
        """
        import check_graded_evidence
        from check_platform_independence import SEARCH_SUFFIXES, _is_allowed, is_graded_evidence

        exempted = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in REPO_ROOT.rglob("*")
            if path.is_file()
            and path.suffix in SEARCH_SUFFIXES
            and is_graded_evidence(path.relative_to(REPO_ROOT).as_posix())
        }
        checked = {p.relative_to(REPO_ROOT).as_posix() for p in check_graded_evidence.artefacts()}

        assert exempted == checked, (
            "a file is exempt from the platform scan and not structurally checked, "
            f"or the reverse: {exempted ^ checked}"
        )
        # And every one of them really is exempt by the platform checker itself,
        # not merely by the predicate in isolation.
        assert all(_is_allowed(path) for path in checked)

    def test_eval_reports_are_gitignored_and_therefore_exempt(self) -> None:
        """The exemption for `evals/reports/` is only honest while git ignores it.

        A promoted case's run report embeds the merchant's own policy text — it
        is the evidence the judge scored against — so `make eval` would otherwise
        turn the platform check red on a file that is not in the repository. If
        that directory ever stops being ignored, the exemption becomes a hole and
        this test says so.
        """
        ignored = {
            line.strip().rstrip("/")
            for line in (REPO_ROOT / ".gitignore").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }

        assert "evals/reports" in ignored, (
            "evals/reports/ is no longer gitignored — its platform-scan exemption is now a hole"
        )

    def test_every_shipped_artefact_is_structurally_sound(self) -> None:
        """The check that pays for the exemption, run over what is committed."""
        from check_graded_evidence import scan

        assert scan() == []

    def test_a_platform_field_is_still_refused(self) -> None:
        """The line ADR-0035 draws: a platform *name in merchant prose* is fine;
        a platform *field* is coupling and is refused."""
        from check_graded_evidence import check_artefact

        problems = check_artefact(
            Path("deadbeef.json"),
            {
                "schema_version": 3,
                "_content_hash": "x",
                "entities": {"products": [{"platform": "x"}]},
            },
        )

        assert any("forbidden field" in p for _, p in problems)

    def test_a_raw_payload_nested_in_an_entity_is_refused(self) -> None:
        """`raw` lives inside products, not at the top level — a shallow check
        would pass a file carrying a platform's field names in every one."""
        from check_graded_evidence import check_artefact

        problems = check_artefact(
            Path("deadbeef.json"),
            {"schema_version": 3, "_content_hash": "x", "calls": [{"result": {"raw": {}}}]},
        )

        assert any("forbidden field" in p for _, p in problems)

    def test_pii_output_evidence_is_refused(self) -> None:
        from check_graded_evidence import check_artefact

        problems = check_artefact(
            Path("deadbeef.json"), {"schema_version": 3, "_content_hash": "x", "pii_output": True}
        )

        assert any("customer data" in p for _, p in problems)

    def test_an_unknown_top_level_key_is_refused(self) -> None:
        """An allowlist, because the failure that matters is a field nobody
        thought about reaching a repository."""
        from check_graded_evidence import check_artefact

        problems = check_artefact(
            Path("deadbeef.json"),
            {"schema_version": 3, "_content_hash": "x", "pii_output": False, "surprise": 1},
        )

        assert any("unexpected top-level key" in p for _, p in problems)

    def test_a_mismatched_hash_is_refused(self) -> None:
        from check_graded_evidence import check_artefact

        problems = check_artefact(
            Path("aaaa.json"), {"schema_version": 3, "_content_hash": "bbbb", "pii_output": False}
        )

        assert any("filename does not match" in p for _, p in problems)
