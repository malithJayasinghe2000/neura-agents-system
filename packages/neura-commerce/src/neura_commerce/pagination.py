"""Cursor pagination.

Cursors, never offsets. ``LIMIT/OFFSET`` silently skips and duplicates rows when
the underlying data changes mid-crawl — and a catalogue sync is precisely a long
crawl over data a merchant is actively editing. The bug it produces (a few
products missing from search) is close to undiagnosable after the fact.

Cursors are opaque to callers: their contents are an adapter's business.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


class Cursor(BaseModel):
    """An opaque position marker.

    Encodes to a URL-safe string so it can travel through query parameters and
    be checkpointed in the database for a resumable sync.
    """

    model_config = ConfigDict(extra="forbid")

    #: Adapter-defined. Typically a last-seen id, page number or platform token.
    state: dict[str, Any] = Field(default_factory=dict)

    def encode(self) -> str:
        raw = json.dumps(self.state, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, encoded: str) -> Self:
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(encoded + padding)
        return cls(state=json.loads(raw))

    @classmethod
    def start(cls) -> Self:
        return cls(state={})

    @property
    def is_start(self) -> bool:
        return not self.state


class Page[ItemT](BaseModel):
    """One page of results, plus how to get the next.

    Generic so ``Page[Product]`` and ``Page[Order]`` are distinct types and a
    mix-up is a type error rather than a runtime surprise.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[ItemT] = Field(default_factory=list)
    next_cursor: Cursor | None = Field(default=None, description="None means this is the last page")

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None

    def __len__(self) -> int:
        return len(self.items)

    # Deliberately NO __iter__: Pydantic's BaseModel defines it to yield
    # (field, value) pairs, and overriding it to yield items would break
    # dict(page) and other Pydantic internals in ways that surface far from the
    # cause. Callers use `page.items`, which is clearer anyway.

    @classmethod
    def empty(cls) -> Page[ItemT]:
        """An empty result.

        An empty page is a valid answer, not an error — a search matching nothing
        is the commonest case in a product catalogue.
        """
        return cls(items=[], next_cursor=None)


def clamp_page_size(requested: int | None) -> int:
    """Keep page sizes sane.

    An unbounded limit lets one call pull a merchant's entire catalogue into
    memory, which is a denial-of-service on both us and them.
    """
    if requested is None or requested <= 0:
        return DEFAULT_PAGE_SIZE
    return min(requested, MAX_PAGE_SIZE)
