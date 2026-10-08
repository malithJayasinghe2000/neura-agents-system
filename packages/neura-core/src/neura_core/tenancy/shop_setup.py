"""The shop owner connects their own shop: the token and the check. ADR-0052.

Two small stores, and the token itself:

* **The token** is made here, by NEURA, from the operating system's secure random
  source (§1). The browser never sends one: there is no credential field to fill
  in, to phish or to log. It is returned **once**, to the request that made it.
* **``ShopTokenRepository``** keeps the token made before the shop is connected,
  sealed exactly like a connection's credentials (envelope encryption,
  security-model.md §5). *Connect* takes it and moves it into ``tenant_stores``.
* **``ShopCheckRepository``** keeps each run of the full check, so the screen can
  say when the shop last passed after the job queue has purged the job.

Nothing here can hand a stored token to a screen: the only readers are the
check's worker and *Connect*, and both are on the server.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, desc, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.config import get_settings
from neura_core.crypto import decrypt, encrypt, generate_key, unwrap_dek, wrap_dek
from neura_core.errors import ConfigurationError
from neura_core.ids import SHOP_CHECK, new_id
from neura_core.tenancy.schema import shop_checks, shop_tokens

#: What a shop token starts with. ``fn_`` like every secret NEURA issues
#: (``fn_sk_``, ``fn_pk_``), so a secret scanner and a person can both recognise
#: one in a log or a repository; ``st`` for *shop token*.
# S105: a public prefix, like ``fn_pk_``; the secret is what follows it.
SHOP_TOKEN_PREFIX = "fn_st_"  # noqa: S105

#: Bytes of randomness: 256 bits, the same strength as an API key.
SHOP_TOKEN_BYTES = 32


def new_shop_token() -> str:
    """A fresh shop token. Shown once by the caller, then only ever sealed."""
    return SHOP_TOKEN_PREFIX + secrets.token_urlsafe(SHOP_TOKEN_BYTES)


def seal(tenant_id: str, credentials: dict[str, str], *, kek: str | None = None) -> tuple[str, str]:
    """Encrypt credentials for one tenant: ``(ciphertext, wrapped data key)``.

    The same envelope as ``StoreConnectionRepository.connect``: a fresh data key
    per secret, wrapped under the KEK and bound to the tenant, so a sealed value
    copied into another tenant's row fails to open instead of quietly working.
    """
    key = _kek(kek)
    dek = generate_key()
    ciphertext = encrypt(json.dumps(credentials, sort_keys=True), dek, aad=tenant_id.encode())
    return ciphertext, wrap_dek(dek, key, tenant_id=tenant_id)


def unseal(
    tenant_id: str, ciphertext: str, wrapped: str, *, kek: str | None = None
) -> dict[str, str]:
    """The inverse of :func:`seal`. Plaintext lives only in the caller's memory."""
    dek = unwrap_dek(wrapped, _kek(kek), tenant_id=tenant_id)
    decoded: dict[str, str] = json.loads(decrypt(ciphertext, dek, aad=tenant_id.encode()))
    return decoded


def _kek(kek: str | None) -> str:
    value = kek or get_settings().kek
    if value == "change-me":
        raise ConfigurationError(
            "NEURA_KEK is still the placeholder, so a shop token would be encrypted "
            "under a key that is published in .env.example. Generate one with "
            "`neura_core.crypto.generate_key()`.",
        )
    return value


class ShopTokenRepository:
    """The token made before the shop is connected. One per tenant."""

    def __init__(self, session: AsyncSession, *, kek: str | None = None) -> None:
        self._session = session
        self._kek = kek

    async def make(self, tenant_id: str, *, made_by: str) -> str:
        """Make a token, seal it, and return it **once**. Replaces any earlier one."""
        token = new_shop_token()
        ciphertext, wrapped = seal(tenant_id, {"token": token}, kek=self._kek)
        statement = pg_insert(shop_tokens).values(
            tenant_id=tenant_id,
            credentials=ciphertext,
            wrapped_dek=wrapped,
            made_by=made_by,
            made_at=datetime.now(UTC),
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[shop_tokens.c.tenant_id],
                set_={
                    "credentials": statement.excluded.credentials,
                    "wrapped_dek": statement.excluded.wrapped_dek,
                    "made_by": statement.excluded.made_by,
                    "made_at": statement.excluded.made_at,
                },
            )
        )
        return token

    async def made_at(self, tenant_id: str) -> datetime | None:
        """When the waiting token was made, or ``None``. Never the token."""
        value = (
            await self._session.execute(
                select(shop_tokens.c.made_at).where(shop_tokens.c.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        return value

    async def credentials(self, tenant_id: str) -> dict[str, str] | None:
        """The waiting token, opened. For the check's worker and *Connect* only."""
        row = (
            await self._session.execute(
                select(shop_tokens.c.credentials, shop_tokens.c.wrapped_dek).where(
                    shop_tokens.c.tenant_id == tenant_id
                )
            )
        ).first()
        if row is None:
            return None
        return unseal(tenant_id, str(row.credentials), str(row.wrapped_dek), kek=self._kek)

    async def discard(self, tenant_id: str) -> None:
        await self._session.execute(delete(shop_tokens).where(shop_tokens.c.tenant_id == tenant_id))


class ShopCheckRepository:
    """Each run of the full check. Holds findings, never a token."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, tenant_id: str, *, address: str, store_id: str | None, requested_by: str
    ) -> str:
        check_id = new_id(SHOP_CHECK)
        await self._session.execute(
            shop_checks.insert().values(
                id=check_id,
                tenant_id=tenant_id,
                store_id=store_id,
                address=address,
                requested_by=requested_by,
                requested_at=datetime.now(UTC),
            )
        )
        return check_id

    async def get(self, tenant_id: str, check_id: str) -> dict[str, Any] | None:
        row = (
            await self._session.execute(
                select(shop_checks).where(
                    shop_checks.c.tenant_id == tenant_id, shop_checks.c.id == check_id
                )
            )
        ).first()
        return None if row is None else _payload(row)

    async def finish(self, check_id: str, *, result: dict[str, Any], failed: bool = False) -> None:
        await self._session.execute(
            update(shop_checks)
            .where(shop_checks.c.id == check_id)
            .values(
                status="failed" if failed else "done",
                result=result,
                finished_at=datetime.now(UTC),
            )
        )

    async def attach(self, tenant_id: str, check_id: str, *, store_id: str) -> None:
        """Make the check that let a shop connect that connection's first check.

        *Connect* calls this, so the connected page opens on the clean check the
        owner just saw instead of *"Not checked yet"*.
        """
        await self._session.execute(
            update(shop_checks)
            .where(shop_checks.c.tenant_id == tenant_id, shop_checks.c.id == check_id)
            .values(store_id=store_id)
        )

    async def latest(
        self, tenant_id: str, *, store_id: str | None, finished_only: bool = False
    ) -> dict[str, Any] | None:
        """The newest check of one connection, or of the shop before it is connected."""
        query = select(shop_checks).where(shop_checks.c.tenant_id == tenant_id)
        query = query.where(
            shop_checks.c.store_id.is_(None)
            if store_id is None
            else shop_checks.c.store_id == store_id
        )
        if finished_only:
            query = query.where(shop_checks.c.status != "pending")
        row = (
            await self._session.execute(query.order_by(desc(shop_checks.c.requested_at)).limit(1))
        ).first()
        return None if row is None else _payload(row)


def _payload(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "store_id": row.store_id,
        "address": str(row.address),
        "status": str(row.status),
        "result": row.result,
        "requested_at": row.requested_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }
