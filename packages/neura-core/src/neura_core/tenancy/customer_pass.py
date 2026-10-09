"""A signed-in shopper's pass, and the shop's secret that signs it. ADR-0057.

The chat box cannot be trusted to name its own customer: anyone can edit a page.
Only the shop knows who is signed in, so the shop's **server** writes a short-lived
**customer pass** into the page for a signed-in customer, signed with a secret only
it and NEURA hold. NEURA checks it here, in code, on every message (Rule 3), and a
pass that passes names the turn's customer.

* **The pass** is a JSON Web Token signed with HMAC-SHA256, carrying exactly
  ``sub`` (the customer's id as the bridge sends it), ``iat`` and ``exp``, and
  lasting at most :data:`MAX_PASS_LIFETIME` (§2). Anything else is refused: an
  algorithm but ``HS256``, a missing claim, a longer life, any other claim (so a
  name or an email is never sent by mistake), an unusable id.
* **The secret** (``fn_cs_…``) is made once per shop by the owner, shown once,
  and kept **sealed** like the shop token (§3): a hash would not do, because the
  secret is needed to check a signature. *Make a new one* replaces it at once.

**Expired is told apart from invalid** (§5), and only for a pass whose signature
is good: the page that sent it learns nothing it did not hold. Neither ever
breaks the chat; the caller treats both as *not signed in*.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.tenancy.schema import customer_secrets
from neura_core.tenancy.shop_setup import seal, unseal

#: What the secret starts with: ``fn_`` like every secret NEURA issues, so a
#: person or a secret scanner can recognise one; ``cs`` for *customer secret*.
# S105: a public prefix; the secret is what follows it.
CUSTOMER_SECRET_PREFIX = "fn_cs_"  # noqa: S105

#: Bytes of randomness: 256 bits, as the shop token and the API keys.
CUSTOMER_SECRET_BYTES = 32

#: The longest a pass may last, from ``iat`` to ``exp`` (ADR-0057 §2). A guess
#: (CLAUDE.md §4): long enough for a page to be read and a question asked, short
#: enough that a copied pass soon stops working.
MAX_PASS_LIFETIME = timedelta(minutes=15)

#: How far apart the shop's clock and ours may be.
CLOCK_LEEWAY = timedelta(seconds=60)

#: The only claims a pass may carry.
PASS_CLAIMS = frozenset({"sub", "iat", "exp"})

#: The only algorithm. Pinned, so ``none`` and every other one are refused.
PASS_ALGORITHM = "HS256"  # noqa: S105 - an algorithm name, not a secret

#: The longest customer id taken, as a product id (G59).
MAX_CUSTOMER_ID = 128

#: A pass longer than this is not one: refused before any work.
MAX_PASS_CHARS = 2048


class PassStatus(StrEnum):
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class PassCheck:
    """What the check found. ``reason`` is for the developer and the log: it
    never repeats the pass or anything inside it."""

    status: PassStatus
    customer_external_id: str | None = None
    reason: str = ""


def new_customer_secret() -> str:
    """A fresh secret. Shown once by the caller, then only ever sealed."""
    return CUSTOMER_SECRET_PREFIX + secrets.token_urlsafe(CUSTOMER_SECRET_BYTES)


def check_customer_pass(
    token: str, secret: str | None, *, now: datetime | None = None
) -> PassCheck:
    """Check a pass against the shop's secret. Never raises."""
    if secret is None:
        return _invalid("this shop has no customer sign-in secret yet")
    if not token or len(token) > MAX_PASS_CHARS:
        return _invalid("not a customer pass")
    if token.strip().startswith(CUSTOMER_SECRET_PREFIX):
        return _invalid(
            "this is the customer sign-in secret itself, not a pass. It must never be in a "
            "web page: make the pass with it on your server, and ask the shop owner to make "
            "a new secret, because this one is now public"
        )
    moment = now or datetime.now(UTC)

    try:
        # The signature and the shape only. Every claim is judged below, once,
        # against `moment`, so the rules read in one place, each with its own
        # reason (a number `sub` would otherwise be the library's *not a
        # customer pass*, G83), and a test's clock is ours. The signature is
        # always checked first: `expired` is said only of a pass this shop
        # really signed.
        claims = jwt.decode(
            token,
            secret,
            algorithms=[PASS_ALGORITHM],
            options={
                "require": sorted(PASS_CLAIMS),
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
                "verify_aud": False,
                "verify_iss": False,
                "verify_sub": False,
                "verify_jti": False,
            },
        )
    except jwt.InvalidAlgorithmError:
        return _invalid(f"signed with an algorithm other than {PASS_ALGORITHM}")
    except jwt.InvalidSignatureError:
        return _invalid("the signature does not match this shop's customer sign-in secret")
    except jwt.MissingRequiredClaimError as exc:
        return _invalid(f"the pass has no {exc.claim} claim")
    except jwt.PyJWTError:
        return _invalid("not a customer pass")

    return _judge(claims, moment)


def _judge(claims: dict[str, object], moment: datetime) -> PassCheck:
    extra = sorted(set(claims) - PASS_CLAIMS)
    if extra:
        return _invalid(f"the pass carries a claim other than sub, iat and exp: {', '.join(extra)}")

    issued, expires = claims["iat"], claims["exp"]
    if (
        isinstance(issued, bool)
        or isinstance(expires, bool)
        or not isinstance(issued, int | float)
        or not isinstance(expires, int | float)
    ):
        return _invalid("iat and exp must be numbers of seconds")
    if expires - issued > MAX_PASS_LIFETIME.total_seconds():
        minutes = int(MAX_PASS_LIFETIME.total_seconds() // 60)
        return _invalid(f"the pass lasts longer than {minutes} minutes")
    stamp = moment.timestamp()
    if issued > stamp + CLOCK_LEEWAY.total_seconds():
        return _invalid("the pass was made in the future: check the shop server's clock")
    if expires < stamp - CLOCK_LEEWAY.total_seconds():
        return PassCheck(PassStatus.EXPIRED, reason="the pass has expired")

    customer = claims["sub"]
    if not isinstance(customer, str):
        # Said plainly, because most shops keep the id as a number (G83). An
        # example, never the pass's own value.
        return _invalid(
            'sub must be text: write the customer\'s id in quotes, "385", not 385, '
            "exactly as the bridge sends it"
        )
    if (
        not customer.strip()
        or len(customer) > MAX_CUSTOMER_ID
        or any(ord(character) < 32 or ord(character) == 127 for character in customer)
    ):
        return _invalid(
            f"sub must be the customer's id as the bridge sends it: text, 1 to "
            f"{MAX_CUSTOMER_ID} characters, no line breaks"
        )
    return PassCheck(PassStatus.VALID, customer_external_id=customer)


def _invalid(reason: str) -> PassCheck:
    return PassCheck(PassStatus.INVALID, reason=reason)


class CustomerSecretRepository:
    """The shop's customer sign-in secret. One per tenant."""

    def __init__(self, session: AsyncSession, *, kek: str | None = None) -> None:
        self._session = session
        self._kek = kek

    async def make(self, tenant_id: str, *, made_by: str) -> str:
        """Make a secret, seal it, and return it **once**. Replaces any earlier
        one, so passes signed with the old one stop working at once."""
        secret = new_customer_secret()
        ciphertext, wrapped = seal(tenant_id, {"secret": secret}, kek=self._kek)
        statement = pg_insert(customer_secrets).values(
            tenant_id=tenant_id,
            secret=ciphertext,
            wrapped_dek=wrapped,
            made_by=made_by,
            made_at=datetime.now(UTC),
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[customer_secrets.c.tenant_id],
                set_={
                    "secret": statement.excluded.secret,
                    "wrapped_dek": statement.excluded.wrapped_dek,
                    "made_by": statement.excluded.made_by,
                    "made_at": statement.excluded.made_at,
                },
            )
        )
        return secret

    async def made_at(self, tenant_id: str) -> datetime | None:
        """When the secret was made, or ``None``. Never the secret."""
        value: datetime | None = (
            await self._session.execute(
                select(customer_secrets.c.made_at).where(customer_secrets.c.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        return value

    async def secret(self, tenant_id: str) -> str | None:
        """The secret, opened. For checking a pass on the server only."""
        row = (
            await self._session.execute(
                select(customer_secrets.c.secret, customer_secrets.c.wrapped_dek).where(
                    customer_secrets.c.tenant_id == tenant_id
                )
            )
        ).first()
        if row is None:
            return None
        return unseal(tenant_id, str(row.secret), str(row.wrapped_dek), kek=self._kek)["secret"]


__all__ = [
    "CLOCK_LEEWAY",
    "CUSTOMER_SECRET_PREFIX",
    "MAX_PASS_LIFETIME",
    "CustomerSecretRepository",
    "PassCheck",
    "PassStatus",
    "check_customer_pass",
    "new_customer_secret",
]
