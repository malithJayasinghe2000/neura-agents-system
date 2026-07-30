"""CARE's prompts — versioned files, loaded and content-hashed.

AGENTS.md: *"Prompts. Files under `prompts/`, never inline strings.
Content-hashed; the hash is recorded per conversation so any past answer can be
traced to the exact prompt that produced it."*

That traceability requirement is not decoration. Six weeks after a shopper
complains about an answer, "which prompt produced this?" must have an exact
answer — and it cannot, if the prompt was an f-string somebody has since edited.
:data:`REVISION` is the fingerprint to record on a conversation; the per-prompt
hashes in :func:`prompt_hashes` say which file changed when it moves.

**A prompt is not a security control.** Nothing in these files decides what CARE
is *permitted* to do — that is the policy engine, in code, where a persuasive
customer message cannot reach it (AGENTS.md rule 3). The prompts describe the
job; the engine enforces the limits. If a safety argument here ever reduces to
"the prompt tells it not to", the argument is void.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

#: Every prompt CARE's graph asks for by name. Listed explicitly rather than
#: globbed, so a renamed file fails at import in front of the developer instead
#: of at runtime as a node quietly running with no system prompt.
REQUIRED = frozenset(
    {
        "route",
        "plan",
        "compose",
        "decline",
        "verify",
        "escalation_message",
        "blocked_message",
    }
)


class PromptError(RuntimeError):
    """A prompt is missing or empty. Raised at load time, never at answer time."""


@cache
def load_prompts() -> dict[str, str]:
    """Every prompt, keyed by name. Ready to hand to ``Runtime(prompts=...)``.

    Cached: the files do not change within a process, and re-reading them per
    turn would put disk I/O on the path of every shopper message.
    """
    prompts: dict[str, str] = {}

    for path in sorted(PROMPT_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            # An empty prompt does not fail — the model just stops following any
            # instruction while still producing fluent text, which is the kind of
            # fault that surfaces in a transcript weeks later.
            raise PromptError(f"prompt file {path.name} is empty")
        prompts[path.stem] = text

    if missing := REQUIRED - prompts.keys():
        raise PromptError(
            f"missing prompt file(s) in {PROMPT_DIR}: "
            f"{', '.join(sorted(name + '.md' for name in missing))}"
        )

    return prompts


@cache
def prompt_hashes() -> dict[str, str]:
    """SHA-256 of each prompt, so a diff can be pinned to a conversation."""
    return {name: _digest(text) for name, text in load_prompts().items()}


@cache
def revision() -> str:
    """One fingerprint covering the whole prompt set.

    Recorded per conversation. Names are hashed alongside bodies, so *adding* a
    prompt changes the revision too — otherwise a new node's prompt would be
    invisible to the audit trail until somebody edited an old file.
    """
    joined = "\n".join(f"{name}:{digest}" for name, digest in sorted(prompt_hashes().items()))
    return _digest(joined)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: Convenience for callers that want the fingerprint without calling anything.
REVISION = revision()

__all__ = ["PROMPT_DIR", "REQUIRED", "REVISION", "PromptError", "load_prompts", "prompt_hashes"]
