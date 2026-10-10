"""ADR-0058 §1 and §2: roles are bundles of permissions, and every route says which.

Two things are held here, without a database:

* **the map** (``neura_core.identity.roles``) opens exactly what the ADR's table
  says for each role, gives the Owner every permission (also one an agent brings
  later, R4), and opens nothing for a role or a permission it does not know;
* **every dashboard route that names a shop declares its permission on the
  route**, and it is the one ``tests/console_permissions.py`` gives it. A route
  that forgets fails here rather than opening to every member by default (the
  ADR's Consequences).

Whether the API then really refuses is ``tests/integration/test_console_roles.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.main import create_app
from neura_core import get_settings
from neura_core.identity.roles import Role, is_permission, role_may
from tests.console_permissions import PERSON_ROUTES, ROLES, ROUTES, WHO


def declared(route: APIRoute) -> list[str]:
    """The permissions a route's dependencies declare, however deeply nested."""
    found: list[str] = []
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        if isinstance(dependency.call, Permitted):
            found.append(dependency.call.permission)
        stack.extend(dependency.dependencies)
    return found


def console_routes(app: FastAPI) -> dict[tuple[str, str], list[str]]:
    """Every route with ``/console/`` in its path, and what each one declares."""
    routes: dict[tuple[str, str], list[str]] = {}
    for context in iter_route_contexts(app.routes):
        path = context.path or ""
        if "/console/" not in path:
            continue
        route = context.original_route
        for method in sorted(context.methods or ()):
            routes[(method, path)] = declared(route) if isinstance(route, APIRoute) else []
    return routes


@pytest.fixture(scope="module")
def mounted() -> Iterator[dict[tuple[str, str], list[str]]]:
    """The routes of the real app, after startup: SELL's are mounted at startup.

    Read, then the app is stopped before any test runs: left running for the
    whole module, its job runner outlives the event loop its database pool was
    made on, and says so in the log.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SMTP_HOST", "")
        get_settings.cache_clear()
        try:
            app = create_app()
            with TestClient(app):
                routes = console_routes(app)
        finally:
            get_settings.cache_clear()
    yield routes


class TestTheRoleMap:
    @pytest.mark.parametrize("permission", sorted(WHO))
    def test_each_role_opens_exactly_what_the_adr_says(self, permission: str) -> None:
        opened = {role for role in ROLES if role_may(role, permission)}
        assert opened == WHO[permission]

    def test_the_roles_are_the_three_the_adr_names(self) -> None:
        assert {role.value for role in Role} == set(ROLES)

    def test_the_owner_gets_a_permission_an_agent_brings_later(self) -> None:
        """R4: the Owner gets every new permission automatically. Support and the
        Developer get it only when an ADR says so."""
        later = "grow:campaigns:write"
        assert role_may("owner", later)
        assert not role_may("support", later)
        assert not role_may("developer", later)

    @pytest.mark.parametrize("role", ["", "admin", "Owner", "owner ", "staff", "marketing"])
    def test_a_role_the_code_does_not_know_opens_nothing(self, role: str) -> None:
        assert not any(role_may(role, permission) for permission in WHO)

    @pytest.mark.parametrize(
        "permission",
        [
            "",
            "*",
            "shop",
            "shop:connection",
            "shop:connection:delete",
            "Shop:connection:write",
            "shop:*:write",
            "shop:connection:write:more",
            " shop:connection:write",
        ],
    )
    def test_a_malformed_permission_opens_nothing_even_for_the_owner(self, permission: str) -> None:
        assert not is_permission(permission)
        assert not role_may("owner", permission)

    def test_every_permission_the_adr_names_is_well_formed(self) -> None:
        assert all(is_permission(permission) for permission in WHO)


class TestEveryRouteDeclaresItsPermission:
    def test_every_shop_route_declares_the_permission_the_adr_gives_it(
        self, mounted: dict[tuple[str, str], list[str]]
    ) -> None:
        wrong = []
        for key, permissions in sorted(mounted.items()):
            if key in PERSON_ROUTES:
                continue
            expected = ROUTES.get(key)
            if expected is None:
                wrong.append(
                    f"{key}: not in tests/console_permissions.py ROUTES; say who may open it"
                )
            elif permissions != [expected]:
                wrong.append(f"{key}: declares {permissions}, the ADR gives it {expected!r}")
        assert not wrong, "\n".join(wrong)

    def test_every_route_in_the_table_is_still_there(
        self, mounted: dict[tuple[str, str], list[str]]
    ) -> None:
        assert set(ROUTES) - set(mounted) == set()

    def test_the_person_routes_name_no_shop_and_need_no_permission(
        self, mounted: dict[tuple[str, str], list[str]]
    ) -> None:
        for method, path in PERSON_ROUTES:
            assert (method, path) in mounted
            assert "{tenant_id}" not in path
            assert mounted[(method, path)] == []

    def test_a_route_that_forgets_is_caught(self) -> None:
        """The check itself, on a planted app: a check that cannot fail checks nothing."""
        app = FastAPI()

        @app.get("/v1/console/shops/{tenant_id}/forgot")
        async def forgot(tenant_id: str) -> dict[str, Any]:
            return {}

        @app.get("/v1/console/shops/{tenant_id}/remembered")
        async def remembered(
            actor: Annotated[ConsoleActor, Depends(Permitted("shop:review:write"))],
        ) -> dict[str, Any]:
            return {}

        found = console_routes(app)
        assert found[("GET", "/v1/console/shops/{tenant_id}/forgot")] == []
        assert found[("GET", "/v1/console/shops/{tenant_id}/remembered")] == ["shop:review:write"]

    def test_a_permission_that_is_not_well_formed_cannot_be_declared(self) -> None:
        with pytest.raises(ValueError, match="permission"):
            Permitted("conversations")
