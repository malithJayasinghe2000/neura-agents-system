"""Prefixed, sortable identifiers.

ULIDs rather than UUID4: they sort by creation time, which makes them far better
database keys, and they remain unguessable — which matters because a
conversation ID that could be enumerated would be an access-control problem
(docs/architecture/security-model.md §3).

The prefix makes an ID self-describing in logs and support conversations, so
``cnv_...`` is never mistaken for ``tn_...``.
"""

from __future__ import annotations

from typing import Final

from ulid import ULID

TENANT: Final = "tn"
API_KEY: Final = "key"
CONVERSATION: Final = "cnv"
MESSAGE: Final = "msg"
REQUEST: Final = "req"
STORE: Final = "st"
DOCUMENT: Final = "doc"
CHUNK: Final = "chk"
EVENT: Final = "evt"
IDEMPOTENCY: Final = "idk"
NEURA_ENTITY: Final = "ne"


def new_id(prefix: str) -> str:
    """Generate a prefixed ULID, e.g. ``cnv_01J8XYZ...``."""
    return f"{prefix}_{ULID()}"


def is_valid(value: str, prefix: str) -> bool:
    """Cheap shape check — does not prove the ID exists."""
    marker = f"{prefix}_"
    if not value.startswith(marker):
        return False
    try:
        ULID.from_str(value[len(marker) :])
    except ValueError:
        return False
    return True
