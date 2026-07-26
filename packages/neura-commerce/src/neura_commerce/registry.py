"""Adapter registry.

Where the core finds adapters **without importing them**. That indirection is
the whole point: ``neura_commerce`` must never import ``neura_adapters``, or the
platform-independence claim is false and CI fails the build.

Adapters register themselves — via an entry point, or explicitly in tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from neura_commerce.protocol import CommerceAdapter
from neura_core import get_logger
from neura_domain import Capability

log = get_logger(__name__)

ENTRY_POINT_GROUP = "neura.adapters"

AdapterFactory = Callable[..., CommerceAdapter]


@dataclass(frozen=True, slots=True)
class RegisteredAdapter:
    platform: str
    factory: AdapterFactory
    capabilities: frozenset[Capability]


class AdapterRegistry:
    """Platform name -> how to build an adapter for it."""

    def __init__(self) -> None:
        self._adapters: dict[str, RegisteredAdapter] = {}
        self._discovered = False

    def register(
        self,
        platform: str,
        factory: AdapterFactory,
        capabilities: frozenset[Capability],
    ) -> None:
        if platform in self._adapters:
            log.warning("adapter_already_registered", platform=platform, detail="overwriting")
        self._adapters[platform] = RegisteredAdapter(platform, factory, capabilities)

    def discover(self) -> None:
        """Load adapters declared via entry points. Idempotent.

        A broken adapter package is logged and skipped rather than taking down
        the process — one bad connector must not deny service to every other
        tenant.
        """
        if self._discovered:
            return

        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                adapter_cls = ep.load()
                self.register(
                    platform=adapter_cls.platform,
                    factory=adapter_cls,
                    capabilities=adapter_cls.capabilities,
                )
            except Exception as exc:
                log.error("adapter_discovery_failed", entry_point=ep.name, error=str(exc))

        self._discovered = True
        log.info("adapters_discovered", platforms=sorted(self._adapters))

    def create(self, platform: str, **config: Any) -> CommerceAdapter:
        self.discover()
        registered = self._adapters.get(platform)
        if registered is None:
            raise KeyError(
                f"No adapter for platform {platform!r}. Available: {sorted(self._adapters)}"
            )
        return registered.factory(**config)

    def capabilities_of(self, platform: str) -> frozenset[Capability]:
        """Declared capabilities without instantiating anything.

        Lets the UI show what a platform supports before a merchant has entered
        any credentials.
        """
        self.discover()
        registered = self._adapters.get(platform)
        if registered is None:
            raise KeyError(f"No adapter for platform {platform!r}")
        return registered.capabilities

    def platforms(self) -> list[str]:
        self.discover()
        return sorted(self._adapters)

    def reset_for_testing(self) -> None:
        self._adapters.clear()
        self._discovered = False


#: Process-wide registry.
registry = AdapterRegistry()
