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
