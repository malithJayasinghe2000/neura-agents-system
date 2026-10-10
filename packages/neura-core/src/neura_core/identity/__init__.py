"""Human identity — the first person-shaped thing in the system (ADR-0026).

Everything else here authenticates a *program* holding a bearer token. This
subpackage authenticates a *human* holding an inbox, and maps them to the
tenants they may act for. **The mapping is code, never a claim the browser
makes** (`AGENTS.md` rule 3), and the cookie names the person and nothing else
so that access stays withdrawable.
"""

from __future__ import annotations

from neura_core.identity.login import (
    TOKEN_TTL,
    Membership,
    SignInRequest,
    may_act_for,
    memberships_for,
    redeem,
    request_sign_in_link,
)
from neura_core.identity.roles import Role, is_permission, role_may
from neura_core.identity.schema import (
    LOGIN_TOKENS,
    MEMBERSHIPS,
    USERS,
    login_tokens,
    memberships,
    users,
)
from neura_core.identity.session import (
    COOKIE_NAME,
    SESSION_TTL,
    Session,
    issue,
    verify,
)

__all__ = [
    "COOKIE_NAME",
    "LOGIN_TOKENS",
    "MEMBERSHIPS",
    "SESSION_TTL",
    "TOKEN_TTL",
    "USERS",
    "Membership",
    "Role",
    "Session",
    "SignInRequest",
    "is_permission",
    "issue",
    "login_tokens",
    "may_act_for",
    "memberships",
    "memberships_for",
    "redeem",
    "request_sign_in_link",
    "role_may",
    "users",
    "verify",
]
