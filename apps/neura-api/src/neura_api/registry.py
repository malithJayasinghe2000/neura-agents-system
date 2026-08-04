"""Agent discovery.

Agents register through Python entry points (``neura.agents``), so adding one
never touches a shared registry file that everybody conflicts on
(docs/architecture/tenancy-and-packaging.md §2.5).

Discovery is separate from *entitlement*: this finds every agent installed in the
deployment; whether a given tenant may use one is decided per request from
``tenants.enabled_agents``.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from neura_agent_core.serving import RUNNER_ENTRY_POINT_GROUP
from neura_core import get_logger

log = get_logger(__name__)

_GROUP = "neura.agents"


@dataclass(frozen=True, slots=True)
class DiscoveredAgent:
    key: str
    name: str
    version: str
    route_prefix: str
    manifest: Any


def discover_runners() -> dict[str, Any]:
    """Load every installed agent *runner*, keyed by agent key.

    The third discovery seam of the same shape — ``neura.agents`` for manifests,
    ``neura.eval_targets`` for the harness, ``neura.agent_runners`` for this. The
    alternative was ``from neura_agent_care import ...`` in a route handler,
    which would make adding agent #2 an edit to the API and would put a product
    name in the one package that must stay ignorant of them.

    Built once, at startup. A runner compiles its graph in its constructor, and
    doing that per request would put graph construction inside a shopper's
    latency.

    A runner whose key disagrees with its entry-point name is **refused**: the
    key decides which routes it is mounted under, which entitlement is checked
    and which agent is billed, so a disagreement would bill one agent for
    another's work.
    """
    found: dict[str, Any] = {}

    for ep in entry_points(group=RUNNER_ENTRY_POINT_GROUP):
        try:
            runner = ep.load()()
            if runner.key != ep.name:
                log.error(
                    "agent_runner_key_mismatch",
                    entry_point=ep.name,
                    runner_key=runner.key,
                    detail="refused; usage would be attributed to the wrong agent",
                )
                continue
            found[runner.key] = runner
        except Exception as exc:
            # Logged and skipped rather than fatal: one broken connector must
            # not deny service to every other agent in the deployment. The
            # route then answers AGENT_NOT_RUNNABLE, which says "we have it and
            # it is broken" rather than "we do not have it".
            log.error("agent_runner_failed", entry_point=ep.name, error=str(exc))

    log.info("agent_runners_discovered", agents=sorted(found))
    return found


def discover_agents() -> dict[str, DiscoveredAgent]:
    """Load every installed agent manifest, keyed by agent key.

    A broken agent package is logged and skipped rather than taking down the
    whole API — one bad agent should not deny service to the others.
    """
    found: dict[str, DiscoveredAgent] = {}

    for ep in entry_points(group=_GROUP):
        try:
            manifest = ep.load()
            found[manifest.key] = DiscoveredAgent(
                key=manifest.key,
                name=manifest.name,
                version=manifest.version,
                route_prefix=manifest.route_prefix,
                manifest=manifest,
            )
        except Exception as exc:
            log.error("agent_discovery_failed", entry_point=ep.name, error=str(exc))

    log.info("agents_discovered", agents=sorted(found))
    return found
