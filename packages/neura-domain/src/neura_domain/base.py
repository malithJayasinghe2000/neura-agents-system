"""Shared primitives for the canonical model.

Three rules encoded here, each for a class of bug we expect
(docs/architecture/commerce-integration.md §2.2):

* **Money is never a float.** Decimal plus an ISO-4217 currency. Float arithmetic
  produces wrong order totals that cannot be reconciled after the fact.
* **External IDs are always strings.** Platforms use integers, UUIDs and prefixed
  slugs; normalising at the boundary removes an entire class of comparison bug.
* **Timestamps are timezone-aware UTC, always.**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DomainModel(BaseModel):
    """Base for every canonical entity."""

    model_config = ConfigDict(
        frozen=False,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


CurrencyCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]


class Money(DomainModel):
    """An amount in a single currency."""

    amount: Decimal
    currency: CurrencyCode

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        # Accept ints/strings from adapters, but never silently accept a float —
        # by the time a float arrives the precision is already lost.
        #
        # ValueError, not TypeError: Pydantic wraps ValueError into a
        # ValidationError, so callers handle one exception type. A TypeError
        # would escape validation entirely and surface as a 500.
        if isinstance(v, float):
            raise ValueError("Money.amount must not be a float; use Decimal or str")
        return v

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


class Address(DomainModel):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    region: str | None = None
    postcode: str | None = None
    country: str | None = Field(default=None, description="ISO-3166 alpha-2 where known")


class CanonicalEntity(DomainModel):
    """Every synced entity carries its provenance.

    ``raw`` deliberately preserves the source payload. No canonical model survives
    contact with every platform; keeping the original means an unmapped field is a
    lookup rather than a full re-sync.
    """

    neura_id: str
    tenant_id: str
    external_id: str
    platform: str
    synced_at: datetime
    raw: dict[str, Any] | None = None

    @field_validator("external_id", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> str:
        return str(v)

    @field_validator("synced_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return v
