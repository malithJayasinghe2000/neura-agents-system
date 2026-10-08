"""neura-commerce — the adapter contract and capability negotiation.

The layer that makes "works with any commerce platform" true. Everything above
speaks only the canonical domain model; adapters translate.

Two mechanisms carry the design:

1. **The CommerceAdapter protocol** — one interface, implemented per platform.
   A Protocol rather than a base class, so a third party can conform without
   importing anything from us.

2. **Capability negotiation** — adapters declare what their platform can do, and
   the agent's tool set is computed from that declaration. A store that cannot
   cancel orders never gets a cancel tool, which is both the integration
   mechanism and a security control: the best defence against tool abuse is not
   registering the tool.

HARD RULE: this package must never import ``neura_adapters``. The core must not
know which platforms exist. Enforced by an import-linter contract and by a CI
check that greps for platform names.
"""

from neura_commerce.conformance import (
    ConformanceReport,
    Finding,
    ProtocolChecks,
    Severity,
    check_adapter,
    run_conformance,
)
from neura_commerce.errors import (
    AdapterAuthError,
    AdapterError,
    AdapterMappingError,
    AdapterRateLimitedError,
    AdapterTimeoutError,
    AdapterUnavailableError,
    CapabilityNotSupportedError,
    EntityNotFoundError,
)
from neura_commerce.identity import EntityKey, EntityMap, EntityMapping, EntityType
from neura_commerce.negotiation import (
    NegotiationResult,
    Requirement,
    describe_gap,
    filter_by_capability,
    negotiate,
)
from neura_commerce.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Cursor,
    Page,
    clamp_page_size,
)
from neura_commerce.protocol import CommerceAdapter, WritableCommerceAdapter
from neura_commerce.queries import HealthStatus, ProductQuery, SyncQuery
from neura_commerce.registry import AdapterRegistry, RegisteredAdapter, registry

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "AdapterAuthError",
    "AdapterError",
    "AdapterMappingError",
    "AdapterRateLimitedError",
    "AdapterRegistry",
    "AdapterTimeoutError",
    "AdapterUnavailableError",
    "CapabilityNotSupportedError",
    "CommerceAdapter",
    "ConformanceReport",
    "Cursor",
    "EntityKey",
    "EntityMap",
    "EntityMapping",
    "EntityNotFoundError",
    "EntityType",
    "Finding",
    "HealthStatus",
    "NegotiationResult",
    "Page",
    "ProductQuery",
    "ProtocolChecks",
    "RegisteredAdapter",
    "Requirement",
    "Severity",
    "SyncQuery",
    "WritableCommerceAdapter",
    "check_adapter",
    "clamp_page_size",
    "describe_gap",
    "filter_by_capability",
    "negotiate",
    "registry",
    "run_conformance",
]
