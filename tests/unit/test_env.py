"""Loading .env into the process environment.

This exists because of a real bug: `make judge-check` reported
"EVAL_JUDGE_* not set" while .env set them perfectly well. Several modules read
configuration with os.getenv, and nothing had loaded the file — so the program
behaved as though a correct config file were empty.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from neura_core.env import find_env_file, load_env, reset_for_testing


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reset_for_testing()
    monkeypatch.chdir(tmp_path)


def _write_env(tmp_path: Path, content: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(content)
    return path


class TestLoading:
    def test_values_reach_os_environ(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_env(tmp_path, "EVAL_JUDGE_MODEL=gemini-2.5-flash\n")
        monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)

        load_env()
        assert os.environ["EVAL_JUDGE_MODEL"] == "gemini-2.5-flash"

    def test_the_first_occurrence_of_a_duplicate_key_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Surprising, and it decided which LLM provider was live for a week.

        Most people read a .env like a shell script, where a later line
        overrides an earlier one. Here the opposite holds — a consequence of
        real environment variables winning — so a block appended to the bottom
        of the file is inert while looking authoritative.
        """
        _write_env(
            tmp_path, "CLOUD_LLM_BASE_URL=https://first\nCLOUD_LLM_BASE_URL=https://second\n"
        )
        monkeypatch.delenv("CLOUD_LLM_BASE_URL", raising=False)

        load_env()
        assert os.environ["CLOUD_LLM_BASE_URL"] == "https://first"

    def test_real_environment_wins_over_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In production there is no .env; values come from the platform.

        A .env able to override those would be a way to accidentally ship
        development settings.
        """
        _write_env(tmp_path, "NEURA_ENV=development\n")
        monkeypatch.setenv("NEURA_ENV", "production")

        load_env()
        assert os.environ["NEURA_ENV"] == "production"

    def test_missing_file_is_not_an_error(self) -> None:
        """The normal case in production."""
        assert load_env() is None

    def test_is_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_env(tmp_path, "SOME_KEY=first\n")
        monkeypatch.delenv("SOME_KEY", raising=False)

        assert load_env() is not None
        assert load_env() is None  # second call is a no-op


class TestParsing:
    def test_comments_and_blank_lines_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_env(tmp_path, "# a comment\n\nKEY_A=value\n\n# another\nKEY_B=other\n")
        for key in ("KEY_A", "KEY_B"):
            monkeypatch.delenv(key, raising=False)

        load_env()
        assert os.environ["KEY_A"] == "value"
        assert os.environ["KEY_B"] == "other"

    def test_inline_comments_are_stripped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Our own .env has these — `OTEL_ENABLED=false   # no collector`."""
        _write_env(tmp_path, "OTEL_ENABLED=false     # nothing listening locally\n")
        monkeypatch.delenv("OTEL_ENABLED", raising=False)

        load_env()
        assert os.environ["OTEL_ENABLED"] == "false"

    def test_quoted_values_keep_a_hash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A '#' inside quotes is part of the value, not a comment.

        Matters: API keys and passwords genuinely contain '#'.
        """
        _write_env(tmp_path, 'SECRET="abc#def"\n')
        monkeypatch.delenv("SECRET", raising=False)

        load_env()
        assert os.environ["SECRET"] == "abc#def"

    def test_urls_survive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A URL contains '//' and ':' — it must not be mangled."""
        url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        _write_env(tmp_path, f"EVAL_JUDGE_BASE_URL={url}\n")
        monkeypatch.delenv("EVAL_JUDGE_BASE_URL", raising=False)

        load_env()
        assert os.environ["EVAL_JUDGE_BASE_URL"] == url

    def test_values_containing_equals_are_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Base64 keys end in '=' padding — splitting on every '=' would corrupt them."""
        _write_env(tmp_path, "NEURA_KEK=q2cVabc123+/xyz=\n")
        monkeypatch.delenv("NEURA_KEK", raising=False)

        load_env()
        assert os.environ["NEURA_KEK"] == "q2cVabc123+/xyz="

    def test_malformed_lines_are_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_env(tmp_path, "this line has no equals sign\nGOOD_KEY=value\n")
        monkeypatch.delenv("GOOD_KEY", raising=False)

        load_env()
        assert os.environ["GOOD_KEY"] == "value"


class TestDiscovery:
    def test_found_from_a_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Commands must work from anywhere in the repo, not only the root."""
        _write_env(tmp_path, "KEY_FROM_ROOT=yes\n")
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "packages" / "neura-llm"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        monkeypatch.delenv("KEY_FROM_ROOT", raising=False)

        load_env()
        assert os.environ["KEY_FROM_ROOT"] == "yes"

    def test_search_stops_at_the_repository_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Never escape upward into $HOME and pick up an unrelated .env."""
        _write_env(tmp_path, "OUTSIDE=leaked\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        monkeypatch.chdir(repo)

        assert find_env_file() is None
