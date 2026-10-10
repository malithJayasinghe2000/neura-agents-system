"""Reading and writing tenancy rows.

Every method here takes a session that is already tenant-scoped, so none of them
writes a ``WHERE tenant_id`` for safety — Row-Level Security does that, and a
filter written by hand would be the second-best of two defences pretending to be
the first. Where a tenant id appears in a query it is there for the index or for
the primary key, and the code says so.

The one exception is :meth:`ApiKeyRepository.find_by_token`, which runs on the
credential session described in :meth:`Database.credential_session` — the only
transaction in the system that legitimately does not know its tenant yet.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import bindparam, delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.config import get_settings
from neura_core.crypto import decrypt, encrypt, generate_key, unwrap_dek, wrap_dek
from neura_core.errors import ConfigurationError, NotFoundError
from neura_core.ids import API_KEY, STORE, TENANT, new_id
from neura_core.observation.models import OBSERVE_WRITE
from neura_core.tenancy import keys
from neura_core.tenancy.keys import ApiKeyKind, IssuedKey, KeyEnvironment, public_key_may_hold
from neura_core.tenancy.models import ApiKey, Tenant, TenantConfig, TenantStatus
from neura_core.tenancy.modes import TurnMode
from neura_core.tenancy.schema import api_keys, tenant_stores, tenants


class TenantRepository:
    """Tenant records and their configuration."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        tenant_id: str | None = None,
        enabled_agents: Sequence[str] = (),
        config: TenantConfig | None = None,
        status: TenantStatus = TenantStatus.ACTIVE,
    ) -> Tenant:
        """Create a tenant.

        The session must already be scoped to the id being created — the
        ``WITH CHECK`` half of the policy refuses a row belonging to anyone
        else, which is what stops a compromised request creating a tenant it
        would then be able to read.
        """
        new_tenant_id = tenant_id or new_id(TENANT)
        settings = config or TenantConfig()

        await self._session.execute(
            pg_insert(tenants).values(
                tenant_id=new_tenant_id,
                name=name,
                status=status.value,
                enabled_agents=sorted(set(enabled_agents)),
                config=_config_to_jsonb(settings),
            )
        )
        created = await self.get(new_tenant_id)
        if created is None:  # pragma: no cover — RLS would have raised first
            raise ConfigurationError(
                "the tenant was inserted but is not readable; the session is "
                "scoped to a different tenant than the one being created."
            )
        return created

    async def get(self, tenant_id: str) -> Tenant | None:
        row = (
            await self._session.execute(select(tenants).where(tenants.c.tenant_id == tenant_id))
        ).first()
        return None if row is None else _tenant_from_row(row)

    async def require(self, tenant_id: str) -> Tenant:
        tenant = await self.get(tenant_id)
        if tenant is None:
            raise NotFoundError("No such tenant.", details={"tenant_id": tenant_id})
        return tenant

    async def set_config(self, tenant_id: str, config: TenantConfig) -> Tenant:
        await self._session.execute(
            update(tenants)
            .where(tenants.c.tenant_id == tenant_id)
            .values(config=_config_to_jsonb(config), updated_at=func.now())
        )
        return await self.require(tenant_id)

    async def set_mode(self, tenant_id: str, mode: TurnMode) -> Tenant:
        """Practice mode on or off, and nothing else (ADR-0054 §5).

        One key merged into the stored settings rather than the whole settings
        written back: ``TenantConfig`` drops keys it does not know, on purpose
        (``modes.py``), so a read-modify-write here could erase a setting a
        newer deployment wrote. ``shadow_intents`` is left as it is.
        """
        patch = bindparam("mode_patch", {"mode": mode.value}, type_=JSONB)
        await self._session.execute(
            update(tenants)
            .where(tenants.c.tenant_id == tenant_id)
            .values(config=tenants.c.config.op("||")(patch), updated_at=func.now())
        )
        return await self.require(tenant_id)

    async def set_contact(self, tenant_id: str, *, email: str | None, phone: str | None) -> Tenant:
        """The shop's own contact details, named in every handover (ADR-0055).

        Merged like :meth:`set_mode`, two keys and nothing else. ``None`` is
        written as JSON ``null``: the owner cleared the field.
        """
        patch = bindparam(
            "contact_patch", {"contact_email": email, "contact_phone": phone}, type_=JSONB
        )
        await self._session.execute(
            update(tenants)
            .where(tenants.c.tenant_id == tenant_id)
            .values(config=tenants.c.config.op("||")(patch), updated_at=func.now())
        )
        return await self.require(tenant_id)

    async def set_enabled_agents(self, tenant_id: str, agents: Sequence[str]) -> Tenant:
        """The upgrade path from tenancy-and-packaging.md §3.2: a row, not a deploy."""
        await self._session.execute(
            update(tenants)
            .where(tenants.c.tenant_id == tenant_id)
            .values(enabled_agents=sorted(set(agents)), updated_at=func.now())
        )
        return await self.require(tenant_id)

    async def set_status(self, tenant_id: str, status: TenantStatus) -> Tenant:
        await self._session.execute(
            update(tenants)
            .where(tenants.c.tenant_id == tenant_id)
            .values(status=status.value, updated_at=func.now())
        )
        return await self.require(tenant_id)

    async def set_dpa_signed_at(self, tenant_id: str, signed_at: datetime | None) -> Tenant:
        """Record a data-processing agreement, or ``None`` to withdraw it.

        **Withdrawing does not delete anything by itself.** Whoever withdraws
        must also remove what the agreement permitted — ``tenant_admin.py dpa
        --withdraw`` does both in one transaction — and the retention sweep
        deletes every observed event of a tenant with no agreement, so a path
        that forgets is corrected within a day rather than never.
        """
        await self._session.execute(
            update(tenants)
            .where(tenants.c.tenant_id == tenant_id)
            .values(dpa_signed_at=signed_at, updated_at=func.now())
        )
        return await self.require(tenant_id)


class ApiKeyRepository:
    """Issuing, listing, revoking and — the interesting one — finding a key."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(
        self,
        tenant_id: str,
        *,
        kind: ApiKeyKind = ApiKeyKind.SECRET,
        scopes: Sequence[str] = (),
        name: str = "",
        allowed_origins: Sequence[str] = (),
        expires_at: datetime | None = None,
        environment: KeyEnvironment | None = None,
    ) -> tuple[ApiKey, IssuedKey]:
        """Mint a key and store only its hash.

        Returns the record *and* the plaintext, in that order, because the
        plaintext exists exactly once and the caller has to decide deliberately
        what to do with it. Nothing here logs it: the redaction filter would
        catch an ``fn_sk_`` in a log line, and relying on that would be relying
        on a safety net rather than on not falling.
        """
        if kind is ApiKeyKind.PUBLIC and not allowed_origins:
            # A browser key with no origin allowlist is a key anyone may use
            # from anywhere. Refused at issue time, where it is a typo, rather
            # than at request time, where it is an incident.
            raise ConfigurationError(
                "a public (fn_pk_) key must be issued with at least one allowed "
                "origin — it is served to browsers and is not a secret.",
            )

        if kind is ApiKeyKind.PUBLIC:
            # G80: a public key is in every page's source. Refused here, where
            # it is a typo, rather than found in a page where anyone can copy it.
            refused = sorted(s for s in set(scopes) if not public_key_may_hold(s))
            if refused:
                raise ConfigurationError(
                    "a public (fn_pk_) key may hold only what the chat box uses, because "
                    f"anyone can read it in the page; not {', '.join(refused)}. Use a "
                    "secret key on a server for these.",
                )

        if OBSERVE_WRITE in scopes:
            await self._check_observer(tenant_id, kind)

        env = environment or _environment_for_deployment()
        issued = keys.generate(kind, env)
        record_id = new_id(API_KEY)

        await self._session.execute(
            pg_insert(api_keys).values(
                id=record_id,
                tenant_id=tenant_id,
                kind=kind.value,
                name=name,
                token_prefix=issued.token_prefix,
                token_hash=issued.token_hash,
                scopes=sorted(set(scopes)),
                allowed_origins=sorted(set(allowed_origins)),
                expires_at=expires_at,
            )
        )

        stored = await self.get(record_id)
        if stored is None:  # pragma: no cover — RLS would have raised first
            raise ConfigurationError(
                "the API key was inserted but is not readable; the session is "
                "scoped to a different tenant than the key."
            )
        return stored, issued

    async def _check_observer(self, tenant_id: str, kind: ApiKeyKind) -> None:
        """Two refusals at issue time, where each is a typo rather than an incident.

        **A browser key may never send events** (ADR-0044 §2): *"no script of
        ours runs in a shopper's browser"*, and an ``fn_pk_`` key is served to
        browsers by design. **And no key may send them for a tenant without a
        data-processing agreement** (ADR-0042 §2), so a shop that has none has no
        credential to send with — the events never leave it.

        The route checks both again: an agreement can be withdrawn after a key
        was issued.
        """
        if kind is not ApiKeyKind.SECRET:
            raise ConfigurationError(
                f"`{OBSERVE_WRITE}` may be held only by a secret (fn_sk_) key — events "
                "come from the shop's server, never from a shopper's browser (ADR-0044 §2).",
            )
        signed_at = await self._session.scalar(
            select(tenants.c.dpa_signed_at).where(tenants.c.tenant_id == tenant_id)
        )
        if signed_at is None:
            raise ConfigurationError(
                f"`{OBSERVE_WRITE}` needs a data-processing agreement on record for this "
                "tenant (ADR-0042 §2). Record one with `make tenant-dpa TENANT=...` first.",
            )

    async def get(self, key_id: str) -> ApiKey | None:
        row = (await self._session.execute(select(api_keys).where(api_keys.c.id == key_id))).first()
        return None if row is None else _api_key_from_row(row)

    async def list_for(self, tenant_id: str) -> list[ApiKey]:
        rows = (
            await self._session.execute(
                select(api_keys)
                .where(api_keys.c.tenant_id == tenant_id)
                .order_by(api_keys.c.created_at.desc())
            )
        ).all()
        return [_api_key_from_row(row) for row in rows]

    async def find_by_token(self, token: str) -> ApiKey | None:
        """Look up the key a caller presented.

        Runs on a credential session, which can see this row and nothing else.
        The comparison is on the hash: the plaintext is not stored and never was.
        """
        token_hash = keys.fingerprint(token)
        row = (
            await self._session.execute(select(api_keys).where(api_keys.c.token_hash == token_hash))
        ).first()
        if row is None:
            return None
        # Belt and braces: the row came back because the database matched the
        # hash, and this confirms it in code that does not depend on the policy
        # being right.
        if not keys.matches(token, str(row.token_hash)):  # pragma: no cover
            return None
        return _api_key_from_row(row)

    async def revoke(self, key_id: str, *, at: datetime | None = None) -> ApiKey:
        """Revocation is a timestamp, not a delete.

        A deleted key leaves no answer to "what did this key do, and when did we
        stop it?" — which is the first question after an incident.
        """
        await self._session.execute(
            update(api_keys)
            .where(api_keys.c.id == key_id)
            .where(api_keys.c.revoked_at.is_(None))
            .values(revoked_at=at or datetime.now(UTC))
        )
        key = await self.get(key_id)
        if key is None:
            raise NotFoundError("No such API key.", details={"key_id": key_id})
        return key

    async def touch(
        self,
        key_id: str,
        *,
        at: datetime | None = None,
        not_before: datetime | None = None,
    ) -> None:
        """Record that the key was used, for stale-key detection.

        ``not_before`` throttles the write: without it every authenticated
        request costs an ``UPDATE`` on a hot row, which is a real cost for a
        field whose entire purpose is answering "has anyone used this key in the
        last few months?".
        """
        moment = at or datetime.now(UTC)
        statement = update(api_keys).where(api_keys.c.id == key_id).values(last_used_at=moment)
        if not_before is not None:
            statement = statement.where(
                api_keys.c.last_used_at.is_(None) | (api_keys.c.last_used_at < not_before)
            )
        await self._session.execute(statement)


class StoreConnectionRepository:
    """A tenant's store credentials, encrypted at rest.

    Envelope encryption (security-model.md §5): a fresh data key per connection,
    wrapped under the KEK from the environment and bound to the tenant, so a
    wrapped key copied into another tenant's row fails to unwrap instead of
    quietly working. The KEK is never in this database, which is what makes a
    dump of it worthless.
    """

    def __init__(self, session: AsyncSession, *, kek: str | None = None) -> None:
        self._session = session
        self._kek = kek

    async def connect(
        self,
        tenant_id: str,
        *,
        platform: str,
        base_url: str,
        credentials: dict[str, str],
        set_by: str | None = None,
    ) -> str:
        """Store (or replace) one store connection. Returns its id.

        ``set_by``: the console user who made the token in ``credentials``, when a
        person did (ADR-0058 §6).
        """
        dek = generate_key()
        kek = self._require_kek()
        ciphertext = encrypt(json.dumps(credentials, sort_keys=True), dek, aad=tenant_id.encode())

        statement = pg_insert(tenant_stores).values(
            id=new_id(STORE),
            tenant_id=tenant_id,
            platform=platform,
            base_url=base_url,
            credentials=ciphertext,
            wrapped_dek=wrap_dek(dek, kek, tenant_id=tenant_id),
            credentials_set_by=set_by,
        )
        result = await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    tenant_stores.c.tenant_id,
                    tenant_stores.c.platform,
                    tenant_stores.c.base_url,
                ],
                set_={
                    "credentials": statement.excluded.credentials,
                    "wrapped_dek": statement.excluded.wrapped_dek,
                    "credentials_set_by": statement.excluded.credentials_set_by,
                    "status": "active",
                    "updated_at": func.now(),
                },
            ).returning(tenant_stores.c.id)
        )
        return str(result.scalar_one())

    async def credentials_for(self, tenant_id: str, store_id: str) -> dict[str, str]:
        """Decrypt one connection's credentials.

        Plaintext exists only in the caller's memory, only for as long as they
        hold it. Nothing here caches it.
        """
        row = (
            await self._session.execute(select(tenant_stores).where(tenant_stores.c.id == store_id))
        ).first()
        if row is None:
            raise NotFoundError("No such store connection.", details={"store_id": store_id})

        kek = self._require_kek()
        dek = unwrap_dek(str(row.wrapped_dek), kek, tenant_id=tenant_id)
        plaintext = decrypt(str(row.credentials), dek, aad=tenant_id.encode())
        decoded: dict[str, str] = json.loads(plaintext)
        return decoded

    async def list_for(self, tenant_id: str) -> list[dict[str, str]]:
        """Connections, without their secrets. Safe to log and to render."""
        rows = (
            await self._session.execute(
                select(
                    tenant_stores.c.id,
                    tenant_stores.c.platform,
                    tenant_stores.c.base_url,
                    tenant_stores.c.status,
                )
                .where(tenant_stores.c.tenant_id == tenant_id)
                .order_by(tenant_stores.c.created_at)
            )
        ).all()
        return [
            {
                "id": str(row.id),
                "platform": str(row.platform),
                "base_url": str(row.base_url),
                "status": str(row.status),
            }
            for row in rows
        ]

    async def replace_credentials(
        self,
        tenant_id: str,
        store_id: str,
        credentials: dict[str, str],
        *,
        set_by: str | None = None,
    ) -> bool:
        """Seal new credentials over an existing connection. ``False`` if no such row.

        *Make a new token* (ADR-0052 §2). Only what NEURA sends changes: the shop's
        bridge keeps accepting the old token until its developer puts the new one
        in, because the bridge, not NEURA, checks it (G49).
        """
        dek = generate_key()
        kek = self._require_kek()
        result = await self._session.execute(
            update(tenant_stores)
            .where(tenant_stores.c.tenant_id == tenant_id, tenant_stores.c.id == store_id)
            .values(
                credentials=encrypt(
                    json.dumps(credentials, sort_keys=True), dek, aad=tenant_id.encode()
                ),
                wrapped_dek=wrap_dek(dek, kek, tenant_id=tenant_id),
                credentials_set_by=set_by,
                updated_at=func.now(),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def credentials_set_at(self, tenant_id: str, store_id: str) -> datetime | None:
        """When this connection's credentials were last written. Never the credentials.

        ``updated_at``: only ``connect`` and ``replace_credentials`` write it.
        """
        value = (
            await self._session.execute(
                select(tenant_stores.c.updated_at).where(
                    tenant_stores.c.tenant_id == tenant_id, tenant_stores.c.id == store_id
                )
            )
        ).scalar_one_or_none()
        return value

    async def credentials_set_by(self, tenant_id: str, store_id: str) -> str | None:
        """Who made this connection's token, when a person did. Never the token."""
        value: str | None = (
            await self._session.execute(
                select(tenant_stores.c.credentials_set_by).where(
                    tenant_stores.c.tenant_id == tenant_id, tenant_stores.c.id == store_id
                )
            )
        ).scalar_one_or_none()
        return value

    async def disconnect(self, store_id: str) -> None:
        await self._session.execute(delete(tenant_stores).where(tenant_stores.c.id == store_id))

    def _require_kek(self) -> str:
        kek = self._kek or get_settings().kek
        if kek == "change-me":
            raise ConfigurationError(
                "NEURA_KEK is still the placeholder, so store credentials would "
                "be encrypted under a key that is published in .env.example. "
                "Generate one with `neura_core.crypto.generate_key()`.",
            )
        return kek


# ── Row translation ──────────────────────────────────────────────────────────


def _environment_for_deployment() -> KeyEnvironment:
    """Production mints ``live`` keys; everywhere else mints ``test`` keys.

    Derived rather than configured, because the one thing this label must never
    do is disagree with the deployment it was issued from.
    """
    return KeyEnvironment.LIVE if get_settings().is_production else KeyEnvironment.TEST


def _config_to_jsonb(config: TenantConfig) -> dict[str, Any]:
    # `mode="json"` so Decimal and frozenset become JSON-native types; asyncpg
    # will not serialise either of them into a JSONB column.
    return config.model_dump(mode="json", exclude_none=True)


def _tenant_from_row(row: Any) -> Tenant:
    return Tenant(
        tenant_id=str(row.tenant_id),
        name=str(row.name),
        status=TenantStatus(row.status),
        enabled_agents=frozenset(row.enabled_agents or ()),
        config=TenantConfig.model_validate(row.config or {}),
        dpa_signed_at=row.dpa_signed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _api_key_from_row(row: Any) -> ApiKey:
    return ApiKey(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        kind=ApiKeyKind(row.kind),
        name=str(row.name),
        token_prefix=str(row.token_prefix),
        scopes=frozenset(row.scopes or ()),
        allowed_origins=tuple(row.allowed_origins or ()),
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )
