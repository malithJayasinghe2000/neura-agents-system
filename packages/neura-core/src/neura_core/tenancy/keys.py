"""Minting and recognising API keys.

Pure functions over strings — no database, no configuration — so the format and
its security properties can be reasoned about, and tested, on their own.

    fn_sk_live_x7Kq2mBv…      server-to-server, full scopes
    fn_pk_live_9Rt4nZa1…      browser widget, chat only, origin-locked

**Three decisions are encoded here** (ADR-0014):

* **The random part is 256 bits** from ``secrets.token_urlsafe``. Everything
  below rests on the key being unguessable; nothing else in this module would
  save a key that was not.
* **Stored as SHA-256, not bcrypt or Argon2.** Those exist to make *low-entropy*
  human passwords expensive to guess. A 256-bit random token has nothing to
  guess, and a deliberately slow hash on the authentication path would be a
  self-inflicted denial of service — every request pays it.
* **The prefix is stored in clear.** A merchant with four keys has to be able to
  tell which one to revoke, and the alternative — showing the whole key again —
  is the thing hashing exists to prevent.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum

#: Every key starts with this. Short, unmistakable in a log, and the reason the
#: redaction filter in ``neura_core.logging`` can recognise a leaked key.
SCHEME = "fn"

#: Bytes of entropy in the random part. 32 bytes → 256 bits → 43 characters of
#: URL-safe base64.
_ENTROPY_BYTES = 32

#: How much of the random part is displayable. Enough to identify a key in a
#: list; 208 bits of the token remain secret even if this column leaks.
_PREFIX_CHARS = 8


class ApiKeyKind(StrEnum):
    """What the key is for, and therefore how much it is trusted."""

    # S105 flags the name as a hardcoded password. It is the two letters that
    # appear in `fn_sk_…`, and renaming the member to satisfy the linter would
    # make the enum stop matching the format it describes.
    SECRET = "sk"  # noqa: S105
    """Server-to-server. Holds whatever scopes it was issued with."""

    PUBLIC = "pk"
    """Shipped to a browser, so treated as public knowledge: chat scopes only,
    and locked to an origin allowlist (api-design.md §2)."""


class KeyEnvironment(StrEnum):
    """Live or test. Present in the key itself so that pasting a test key into
    a production configuration is visible at a glance rather than at 3am."""

    LIVE = "live"
    TEST = "test"


_TOKEN_PATTERN = re.compile(
    rf"^{SCHEME}_(?P<kind>sk|pk)_(?P<env>live|test)_(?P<random>[A-Za-z0-9_-]{{20,}})$"
)


@dataclass(frozen=True, slots=True)
class IssuedKey:
    """A freshly minted key. ``token`` exists exactly once, here.

    It is returned rather than stored so that the caller must decide, visibly,
    what to do with it. Nothing in this package writes it anywhere.
    """

    token: str
    kind: ApiKeyKind
    environment: KeyEnvironment
    token_prefix: str
    token_hash: str


def generate(
    kind: ApiKeyKind = ApiKeyKind.SECRET,
    environment: KeyEnvironment = KeyEnvironment.TEST,
) -> IssuedKey:
    """Mint a key. The plaintext is never returned again after this call."""
    random_part = secrets.token_urlsafe(_ENTROPY_BYTES)
    token = f"{SCHEME}_{kind.value}_{environment.value}_{random_part}"
    return IssuedKey(
        token=token,
        kind=kind,
        environment=environment,
        token_prefix=display_prefix(token),
        token_hash=fingerprint(token),
    )


def fingerprint(token: str) -> str:
    """The stored form. One-way, fixed cost, and the only thing compared."""
    return hashlib.sha256(token.encode()).hexdigest()


def matches(token: str, token_hash: str) -> bool:
    """Constant-time comparison.

    A timing side channel on a 256-bit random token is not a realistic attack —
    but the comparison is one line either way, and a reviewer should not have to
    work out which of the two lines it is.
    """
    return hmac.compare_digest(fingerprint(token), token_hash)


def display_prefix(token: str) -> str:
    """What a merchant sees in a list of their keys: ``fn_sk_live_x7Kq2mBv``."""
    parsed = parse(token)
    if parsed is None:
        raise ValueError("not a well-formed API key")
    kind, environment, random_part = parsed
    return f"{SCHEME}_{kind.value}_{environment.value}_{random_part[:_PREFIX_CHARS]}"


def parse(token: str) -> tuple[ApiKeyKind, KeyEnvironment, str] | None:
    """Recognise a key's shape without touching the database.

    Called before the lookup so that a pasted password, a bearer JWT or an empty
    header costs a regex rather than a query. It proves nothing about whether
    the key exists — that is what the hash comparison is for.
    """
    match = _TOKEN_PATTERN.match(token.strip())
    if match is None:
        return None
    return (
        ApiKeyKind(match.group("kind")),
        KeyEnvironment(match.group("env")),
        match.group("random"),
    )


def is_well_formed(token: str) -> bool:
    return parse(token) is not None
