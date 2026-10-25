"""Turning installed agent manifests into dispatch candidates — [ADR-0031] §2.

Discovery, never import. ``neura.agents`` is the same entry point group the API
resolves, so this sees exactly what the deployment has installed and learns no
agent's name at build time. The moment one is hardcoded here, the third agent is
a refactor rather than a package — which is the argument ``neura-evals`` and
``neura-agent-core`` both already make.

**An agent that does not declare cannot be dispatched to.** It is skipped with a
warning rather than given a generated description: a manifest is the only thing
that makes an agent reachable, and inventing words on its behalf would put the
dispatcher's own guess into the prompt that chooses it.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from neura_core import get_logger
from neura_dispatch.chooser import Candidate

log = get_logger(__name__)

#: Mirrors the API's registry. One discovery mechanism, learned once.
GROUP = "neura.agents"


def installed_candidates() -> tuple[Candidate, ...]:
    """Every installed agent that declares what it answers, sorted by key.

    Sorted so the rendered catalogue is stable: the same shop with the same
    agents must produce the same prompt every time, or a dispatch decision
    cannot be reproduced from a recorded revision.

    A broken manifest is logged and skipped rather than raised — one bad agent
    package must not make every shopper message undispatchable — but it is never
    silent, because "the list got shorter" is not something anyone notices.
    """
    found: list[Candidate] = []

    for entry in sorted(entry_points(group=GROUP), key=lambda e: e.name):
        try:
            manifest = entry.load()
        except Exception as exc:
            log.error("dispatch_candidate_failed_to_load", agent=entry.name, error=str(exc))
            continue

        # An agent no shopper talks to (GROW, ADR-0064) is left out on purpose,
        # and quietly: it declares nothing because it answers nothing, which is
        # not the broken manifest the warning below is for.
        if getattr(manifest, "chat", True) is False:
            continue

        handles = (getattr(manifest, "handles", "") or "").strip()
        if not handles:
            log.warning("dispatch_candidate_declares_nothing", agent=entry.name)
            continue

        found.append(
            Candidate(
                key=manifest.key,
                handles=handles,
                examples=tuple(getattr(manifest, "handles_examples", ()) or ()),
            )
        )

    return tuple(found)


def enabled_candidates(enabled: frozenset[str] | set[str]) -> tuple[Candidate, ...]:
    """The installed candidates this tenant has actually bought.

    The dispatcher only ever chooses between agents the merchant pays for.
    ADR-0031 §4 covers the other direction — a question *for* an agent they have
    not bought goes to a person — and that decision is made after this list, by
    the agent the shopper's question actually needed rather than by trimming the
    list until something fits.
    """
    return tuple(c for c in installed_candidates() if c.key in enabled)


__all__ = ["GROUP", "enabled_candidates", "installed_candidates"]
