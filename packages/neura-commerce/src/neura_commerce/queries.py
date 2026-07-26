"""Query and status types shared by every adapter.

Platform-neutral by construction: nothing here can express a concept only one
platform has, which is what stops the contract drifting toward whichever
platform was implemented first.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from neura_commerce.pagination import DEFAULT_PAGE_SIZE
from neura_domain import Capability


class ProductQuery(BaseModel):
    """Search parameters.

    Every field optional: a store that cannot filter by category simply ignores
    that field, rather than the call failing.
    """

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, description="Free-text search")
    category_ids: list[str] = Field(default_factory=list)
    in_stock_only: bool = False
    limit: int = DEFAULT_PAGE_SIZE
    locale: str | None = None


class SyncQuery(BaseModel):
    """Parameters for a bulk crawl.

    ``updated_since`` is a *request*, not a guarantee. A store that cannot filter
    by timestamp omits ``INCREMENTAL_SYNC`` from its capabilities and we
    full-sync it instead. The contract degrades rather than failing — which is
    what lets simple stores integrate at all.
    """

    model_config = ConfigDict(extra="forbid")

    updated_since: datetime | None = None
    limit: int = DEFAULT_PAGE_SIZE
    locale: str | None = None


class HealthStatus(BaseModel):
    """What a store reports about itself.

    Capabilities are **self-declared** here. This single response drives which
    tools the agent is given, so it is the most consequential thing an adapter
    returns (docs/architecture/commerce-integration.md §4.2).
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    platform: str
    spec_version: str = "1.0"
    capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    detail: str | None = None
    latency_ms: int | None = None

    @property
    def usable(self) -> bool:
        """Reachable *and* able to do something.

        A store that answers but declares no capabilities is up and useless —
        worth distinguishing, because the two need different messages to the
        merchant.
        """
        return self.ok and bool(self.capabilities)
