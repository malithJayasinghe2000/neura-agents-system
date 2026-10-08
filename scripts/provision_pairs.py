"""A tenant, a store and a public pairing key — for `pairs_check.py --live`.

Separate from `widget_check.py`'s `provision` because the scopes differ and
should be seen to differ: a pairing key holds `sell:suggest:read` and **nothing
else**, which is ADR-0040 §1's "different gate" expressed in the one place a
person actually reads it — the thing that provisions the key.
"""

from __future__ import annotations

from typing import Any


async def provision(shop_url: str, shop_token: str, origin: str) -> tuple[str, str]:
    from neura_core import Database, get_database, get_settings
    from neura_core.ids import TENANT, new_id
    from neura_core.tenancy import (
        ApiKeyKind,
        ApiKeyRepository,
        StoreConnectionRepository,
        TenantRepository,
    )

    get_settings.cache_clear()
    get_database.cache_clear()
    db = Database.from_settings()
    tenant_id = new_id(TENANT)

    async with db.tenant_session(tenant_id) as session:
        await TenantRepository(session).create(
            tenant_id=tenant_id, name="pairs check", enabled_agents=["sell"]
        )
        _, issued = await ApiKeyRepository(session).issue(
            tenant_id,
            scopes=["sell:suggest:read"],
            name="pairs-check",
            kind=ApiKeyKind.PUBLIC,
            allowed_origins=[origin.rstrip("/")],
        )
        await StoreConnectionRepository(session).connect(
            tenant_id, platform="generic", base_url=shop_url, credentials={"token": shop_token}
        )
    await db.dispose()
    return tenant_id, issued.token


async def deprovision(tenant_id: str) -> Any:
    """Reuse the widget check's teardown — it already removes every table."""
    from widget_check import deprovision as drop

    return await drop(tenant_id)
