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
#: A person (ADR-0026). Distinct from `TENANT` because the two are not the same
#: thing and conflating them is the mistake the console's whole identity design
#: exists to avoid: one human may own two merchants, and one merchant may
#: eventually be worked by two humans.
USER: Final = "usr"
#: A person's access to one merchant.
MEMBERSHIP: Final = "mem"
#: A sign-in link in flight. Short-lived, single-use.
# S105 reads this as a hardcoded password. It is a three-letter id prefix, and
# the value it prefixes is a ULID, never a secret — the secret is the token
# itself, which is hashed before it reaches any column (`identity/login.py`).
LOGIN_TOKEN: Final = "lgt"  # noqa: S105
#: An Owner's invitation to one person, for one shop (ADR-0058 §4). The id names
#: the invite on the People screen; the link's token is another thing, hashed.
INVITE: Final = "inv"
API_KEY: Final = "key"
CONVERSATION: Final = "cnv"
MESSAGE: Final = "msg"
REQUEST: Final = "req"
STORE: Final = "st"
DOCUMENT: Final = "doc"
CHUNK: Final = "chk"
EVENT: Final = "evt"
IDEMPOTENCY: Final = "idk"
#: One unit of background work. Prefixed like everything else so a job id in a
#: log is never mistaken for the conversation that scheduled it.
JOB: Final = "job"
NEURA_ENTITY: Final = "ne"
WEBHOOK: Final = "whk"
#: One (event, endpoint) pair in the outbox — distinct from the event itself,
#: which keeps its ``evt_`` id across every endpoint and every retry because it
#: is the merchant's dedupe key.
WEBHOOK_DELIVERY: Final = "whd"
#: One run of the full check against a shop's bridge (ADR-0052 §4). Not "chk",
#: which a search-index chunk already uses.
SHOP_CHECK: Final = "shc"


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
