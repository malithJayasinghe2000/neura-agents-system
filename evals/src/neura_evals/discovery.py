"""Finding something real to evaluate, without naming any agent.

Milestone 1.4 built this harness before any agent existed, and the seam it left
was ``EvalTarget``. This module is how the seam gets filled: agents advertise
themselves through a ``neura.eval_targets`` entry point, exactly as they
advertise themselves to the API through ``neura.agents``, and the harness
resolves them at run time.

**Why not just import the agent.** ``neura-evals`` importing ``neura_agent_care``
would mean the shared harness knows which agents exist — the same coupling that
``neura-agent-core`` is forbidden by contract to have, for the same reason. Agent
#2 must not require an edit to anything shared, and the moment one agent is
hardcoded here, the second one is a refactor rather than a package.

Each entry point resolves to a factory ``(llm) -> EvalTarget``. Its module is
also where the agent's datasets live, which is what lets ``make eval`` run every
installed agent's golden cases with no path configured anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol

from neura_core import get_logger
from neura_evals.target import EvalTarget

log = get_logger(__name__)

#: The group agents register under. Mirrors ``neura.agents``, deliberately: one
#: discovery mechanism, learned once.
GROUP = "neura.eval_targets"

#: Where an agent keeps its golden cases, relative to the module the entry point
#: resolves into. A convention rather than a second entry point — one thing to
#: declare, and AGENTS.md already specifies this layout for every agent.
DATASETS_SUBDIR = "datasets"


class TargetFactory(Protocol):
    def __call__(self, llm: Any) -> EvalTarget: ...


@dataclass(frozen=True, slots=True)
class DiscoveredAgent:
    """One installed agent that can be evaluated."""

    key: str
    factory: TargetFactory
    dataset_dir: Path

    def build(self, llm: Any) -> EvalTarget:
        return self.factory(llm)


def discover_agents() -> list[DiscoveredAgent]:
    """Every installed agent advertising an eval target, sorted by key.

    A broken entry point is logged and skipped rather than raised. One agent
    failing to import must not stop the others being measured — but it is never
    silent, because "the suite got smaller" is not something anyone notices.
    """
    found: list[DiscoveredAgent] = []

    for entry in sorted(entry_points(group=GROUP), key=lambda e: e.name):
        try:
            factory = entry.load()
        except Exception as exc:
            log.error("eval_target_failed_to_load", agent=entry.name, error=str(exc))
            continue

        module = getattr(factory, "__module__", "")
        dataset_dir = _dataset_dir(module)

        if dataset_dir is None:
            log.warning("eval_target_has_no_datasets", agent=entry.name, module=module)
            continue

        found.append(DiscoveredAgent(key=entry.name, factory=factory, dataset_dir=dataset_dir))

    return found


def _dataset_dir(module_name: str) -> Path | None:
    """Locate ``datasets/`` next to the module the entry point resolved into."""
    import importlib

    try:
        module = importlib.import_module(module_name)
    except Exception:  # pragma: no cover - the factory already imported
        return None

    origin = getattr(module, "__file__", None)
    if origin is None:
        return None

    candidate = Path(origin).resolve().parent / DATASETS_SUBDIR
    return candidate if candidate.is_dir() else None


__all__ = ["DATASETS_SUBDIR", "GROUP", "DiscoveredAgent", "TargetFactory", "discover_agents"]
