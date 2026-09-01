"""The dispatcher's prompt — a versioned file, loaded and content-hashed.

Same mechanism as CARE's and SELL's, and for the same reason (AGENTS.md): six
weeks after a shopper is sent to the wrong service, *"which prompt produced
this?"* must have an exact answer, and it cannot if the prompt was an f-string
somebody has since edited.

**The prompt here is only half of what the model reads.** The other half is
generated per request from the candidates' own manifest declarations, and that
half is deliberately not a file: it changes when a merchant's enabled agents
change, and it must never be edited to make one agent win. Shared code does not
name an agent — the rendered list is the only place an agent key appears, and it
came from that agent's own manifest ([ADR-0031] §2).

**A prompt is not a control.** Nothing here decides what a service is permitted
to do. The dispatcher chooses a destination; the entitlement check decides
whether that destination may be used, in code, where a persuasive shopper
cannot reach it (AGENTS.md rule 3).
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

#: Listed explicitly rather than globbed, so a renamed file fails at import in
#: front of a developer rather than at dispatch time with no system prompt.
REQUIRED = frozenset({"dispatch"})


class PromptError(RuntimeError):
    """A prompt is missing or empty. Raised at load time, never at answer time."""


@cache
def load_prompts() -> dict[str, str]:
    """Every prompt, keyed by name.

    Cached: the files do not change within a process, and re-reading them per
    message would put disk I/O on the path of every shopper turn.
    """
    prompts: dict[str, str] = {}

    for path in sorted(PROMPT_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            # An empty prompt does not fail — the model simply stops following
            # any instruction while still producing a plausible answer, which is
            # the kind of fault that surfaces in a transcript weeks later.
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
    """Per-file content hashes — which prompt moved, when one changes."""
    return {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        for name, text in load_prompts().items()
    }


@cache
def revision() -> str:
    """One fingerprint for the whole prompt directory.

    Recorded on a dispatch so a decision can be traced to the words that made
    it. A17 is the open question about doing this consistently across the
    agents; there is no reason for a new component to arrive already owing it.
    """
    digest = hashlib.sha256()
    for name, text in sorted(load_prompts().items()):
        digest.update(name.encode("utf-8"))
        digest.update(text.encode("utf-8"))
    return digest.hexdigest()[:16]


__all__ = ["PROMPT_DIR", "REQUIRED", "PromptError", "load_prompts", "prompt_hashes", "revision"]
