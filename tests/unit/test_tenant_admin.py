"""`make tenant-new`: a shop FiveNeurals creates starts in practice mode. ADR-0054 §4.

The one way a shop comes into being (`scripts/tenant_admin.py`), so the rule is
held here, at the door, and not by changing ``TenantConfig.mode``'s default:
that default also decides the mode of a shop whose stored settings never named
one, and changing it would switch such a shop off without anyone pressing
anything.
"""

from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from neura_core.tenancy import TenantConfig, TurnMode

REPO = Path(__file__).resolve().parents[2]


def _tenant_admin() -> Any:
    """`scripts/tenant_admin.py`, loaded by path: a script, not a package."""
    spec = importlib.util.spec_from_file_location("tenant_admin", REPO / "scripts/tenant_admin.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Db:
    @asynccontextmanager
    async def tenant_session(self, tenant_id: str):
        yield object()


async def test_a_new_shop_starts_in_practice_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant_admin()
    made: dict[str, Any] = {}

    class _Tenants:
        def __init__(self, session: object) -> None:
            pass

        async def create(self, **kwargs: Any) -> SimpleNamespace:
            made.update(kwargs)
            return SimpleNamespace(
                tenant_id=kwargs["tenant_id"],
                name=kwargs["name"],
                enabled_agents=frozenset(kwargs["enabled_agents"]),
                config=kwargs.get("config") or TenantConfig(),
            )

    monkeypatch.setattr(module, "TenantRepository", _Tenants)

    assert await module.create_tenant(_Db(), "A New Shop", ["care"]) == 0
    assert made["config"].mode is TurnMode.SHADOW


def test_the_models_default_is_unchanged() -> None:
    """§4: the rule lives at creation, not in the default."""
    assert TenantConfig().mode is TurnMode.LIVE
