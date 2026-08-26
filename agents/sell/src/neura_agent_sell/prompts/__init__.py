"""SELL's prompts — versioned files, loaded and content-hashed.

Same mechanism as CARE's and for the same reason (AGENTS.md): six weeks after a
shopper complains about a recommendation, *"which prompt produced this?"* must
have an exact answer — and it cannot if the prompt was an f-string somebody has
since edited. :data:`REVISION` is the fingerprint recorded on a conversation;
the per-prompt hashes say which file moved when it changes.

**A prompt is not a security control.** Nothing in these files decides what SELL
is *permitted* to do — that is the policy engine, in code, where a persuasive
shopper cannot reach it (AGENTS.md rule 3).

**And nothing in these files decides what may be recommended.** That is
``shortlist``, also in code. `compose.md` tells the model to recommend only from
the shortlist; `respond.py` refuses the draft if it did not. The prompt is the
instruction and the node is the enforcement, and if that ever collapses to only
the prompt, the product's central claim collapses with it.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

#: Every prompt SELL's graph asks for by name. Listed explicitly rather than
#: globbed, so a renamed file fails at import in front of a developer rather
#: than at answer time as a node quietly running with no system prompt.
#:
#: `verify`, `escalation_message` and `blocked_message` are absent because they
#: are the *engine's* prompts, supplied by `neura-agent-core` along with the
#: nodes that use them.
REQUIRED = frozenset({"route", "plan", "compose", "decline", "no_match"})


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
            # An empty prompt does not fail — the model simply stops following
            # any instruction while still producing fluent text, which is the
            # kind of fault that surfaces in a transcript weeks later.
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

    Names are hashed alongside bodies, so *adding* a prompt changes the revision
    too — otherwise a new node's prompt would be invisible to the audit trail
    until somebody edited an old file.
    """
    joined = "\n".join(f"{name}:{digest}" for name, digest in sorted(prompt_hashes().items()))
    return _digest(joined)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: Convenience for callers that want the fingerprint without calling anything.
REVISION = revision()

__all__ = ["PROMPT_DIR", "REQUIRED", "REVISION", "PromptError", "load_prompts", "prompt_hashes"]
