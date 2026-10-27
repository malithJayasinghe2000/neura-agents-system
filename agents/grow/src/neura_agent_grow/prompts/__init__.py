"""GROW's prompts: versioned files, loaded and content-hashed (AGENTS.md).

**A prompt is not a security control.** What reaches the owner's page is decided
by the checks in :mod:`neura_agent_grow.finding`, in code (Rule 3); this file
only describes the job.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

#: Every prompt GROW asks for by name. Listed, not globbed, so a renamed file
#: fails at import rather than as a night job that quietly asked a model nothing.
REQUIRED = frozenset({"find_gap"})


class PromptError(RuntimeError):
    """A prompt is missing or empty. Raised at load time, never at run time."""


@cache
def load_prompts() -> dict[str, str]:
    """Every prompt, keyed by name."""
    prompts: dict[str, str] = {}
    for path in sorted(PROMPT_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise PromptError(f"prompt file {path.name} is empty")
        prompts[path.stem] = text
    if missing := REQUIRED - prompts.keys():
        raise PromptError(
            f"missing prompt file(s) in {PROMPT_DIR}: "
            f"{', '.join(sorted(name + '.md' for name in missing))}"
        )
    return prompts


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@cache
def prompt_hashes() -> dict[str, str]:
    """SHA-256 of each prompt, so a stored gap can be traced to its prompt."""
    return {name: _digest(text) for name, text in load_prompts().items()}


@cache
def revision() -> str:
    """One fingerprint covering the whole prompt set, names included."""
    return _digest(
        "\n".join(f"{name}:{digest}" for name, digest in sorted(prompt_hashes().items()))
    )[:16]


REVISION = revision()

__all__ = ["PROMPT_DIR", "REQUIRED", "REVISION", "PromptError", "load_prompts", "prompt_hashes"]
