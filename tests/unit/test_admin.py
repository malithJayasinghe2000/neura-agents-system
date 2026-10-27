"""ADR-0061 without a database: the admin routes, and the admin's sign-in age.

Held here:

* **every route under ``/v1/admin`` states the admin check on the route**
  (``AdminOnly``), and the set of admin routes is exactly
  ``tests/console_permissions.py``'s ``ADMIN_ROUTES``; a route that forgets is
  caught, shown on a planted app;
* **an admin route declares no shop permission**: being an admin is not a shop
  role (§5);
* **an admin page needs a sign-in from the last 12 hours** (R22).

Whether the API really refuses, and what the database lets an admin read, is
``tests/integration/test_admin.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from neura_api.dependencies import AdminActor, AdminOnly, Permitted
from neura_api.main import create_app
from neura_core import get_settings
from neura_core.identity.admins import ADMIN_FRESH, fresh_enough
from tests.console_permissions import ADMIN_ROUTES


def _guards(route: APIRoute) -> tuple[bool, list[str]]:
    """Whether the route depends on ``AdminOnly``, and any shop permission it declares."""
    admin = False
    permissions: list[str] = []
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        if isinstance(dependency.call, AdminOnly):
            admin = True
        if isinstance(dependency.call, Permitted):
            permissions.append(dependency.call.permission)
        stack.extend(dependency.dependencies)
    return admin, permissions


def admin_routes(app: FastAPI) -> dict[tuple[str, str], tuple[bool, list[str]]]:
    routes: dict[tuple[str, str], tuple[bool, list[str]]] = {}
    for context in iter_route_contexts(app.routes):
        path = context.path or ""
        if not path.startswith("/v1/admin"):
            continue
        route = context.original_route
        for method in sorted(context.methods or ()):
            routes[(method, path)] = _guards(route) if isinstance(route, APIRoute) else (False, [])
    return routes


@pytest.fixture(scope="module")
def mounted() -> Iterator[dict[tuple[str, str], tuple[bool, list[str]]]]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SMTP_HOST", "")
        get_settings.cache_clear()
        try:
            app = create_app()
            with TestClient(app):
                routes = admin_routes(app)
        finally:
            get_settings.cache_clear()
    yield routes


class TestEveryAdminRouteChecksTheAdmin:
    def test_the_admin_routes_are_exactly_the_table(
        self, mounted: dict[tuple[str, str], tuple[bool, list[str]]]
    ) -> None:
        assert set(mounted) == set(ADMIN_ROUTES)

    def test_each_states_the_admin_check_and_no_shop_permission(
        self, mounted: dict[tuple[str, str], tuple[bool, list[str]]]
    ) -> None:
        wrong = [
            f"{key}: admin check {admin}, shop permissions {permissions}"
            for key, (admin, permissions) in sorted(mounted.items())
            if not admin or permissions
        ]
        assert not wrong, "\n".join(wrong)

    def test_a_route_that_forgets_is_caught(self) -> None:
        """The check itself, on a planted app: a check that cannot fail checks nothing."""
        app = FastAPI()

        @app.get("/v1/admin/forgot")
        async def forgot() -> dict[str, Any]:
            return {}

        @app.get("/v1/admin/remembered")
        async def remembered(
            actor: Annotated[AdminActor, Depends(AdminOnly())],
        ) -> dict[str, Any]:
            return {}

        found = admin_routes(app)
        assert found[("GET", "/v1/admin/forgot")] == (False, [])
        assert found[("GET", "/v1/admin/remembered")] == (True, [])


class TestTheAdminSignInAge:
    def test_it_is_12_hours(self) -> None:
        assert timedelta(hours=12) == ADMIN_FRESH

    @pytest.mark.parametrize(
        ("age", "fresh"),
        [
            (timedelta(0), True),
            (timedelta(hours=11, minutes=59), True),
            (timedelta(hours=12), False),
            (timedelta(days=3), False),
        ],
    )
    def test_a_sign_in_older_than_12_hours_is_not_enough(self, age: timedelta, fresh: bool) -> None:
        now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
        assert fresh_enough(now - age, now=now) is fresh
