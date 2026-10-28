"""Who may open each dashboard route: ADR-0058 §2 and console.md §3.8, as data.

**Written from the documents, not from the code's map.** The tests that use this
check the code against it, so it must not be generated from the code: a table
copied out of ``neura_core.identity.roles`` would pass whatever the map said.

Two halves, kept apart because they answer different questions:

* :data:`WHO`: which roles each permission opens (the ADR's table, with the
  names fixed in the build, G88);
* :data:`ROUTES`: which permission each dashboard route needs.

A route added to the API and not to :data:`ROUTES` fails
``tests/unit/test_console_roles.py``, so whoever adds it must say who may open it.
"""

from __future__ import annotations

OWNER = "owner"
SUPPORT = "support"
DEVELOPER = "developer"

ROLES = (OWNER, SUPPORT, DEVELOPER)

CONVERSATIONS = "shop:conversations:read"
REVIEW = "shop:review:write"
SUGGESTIONS = "sell:suggestions:write"
SOLD_OUT = "shop:sold_out:read"
CONNECTION = "shop:connection:write"
CONNECT = "shop:connect:write"
CONTACT = "shop:contact:write"
MODE = "shop:mode:write"
USAGE = "usage:cost:read"
PEOPLE = "people:members:write"
HOME = "shop:home:read"
HANDOVERS = "shop:handovers:write"
GAPS = "shop:gaps:write"
WANTED = "shop:wanted:read"

#: ADR-0058 §2, *The first permissions*, R10's B (the Developer has all of
#: Shop connection, Connect and the contact details included), and R12 (Home is
#: every member's, each seeing only their own work there).
WHO: dict[str, frozenset[str]] = {
    HOME: frozenset({OWNER, SUPPORT, DEVELOPER}),
    CONVERSATIONS: frozenset({OWNER, SUPPORT}),
    REVIEW: frozenset({OWNER, SUPPORT}),
    SUGGESTIONS: frozenset({OWNER}),
    SOLD_OUT: frozenset({OWNER}),
    CONNECTION: frozenset({OWNER, DEVELOPER}),
    CONNECT: frozenset({OWNER, DEVELOPER}),
    CONTACT: frozenset({OWNER, DEVELOPER}),
    MODE: frozenset({OWNER}),
    USAGE: frozenset({OWNER}),
    PEOPLE: frozenset({OWNER}),
    # ADR-0062 §8: answer a handed-over shopper (see their email, Answer by
    # email, Mark as answered). The help desk's work; never the Developer's.
    HANDOVERS: frozenset({OWNER, SUPPORT}),
    # ADR-0064 §5: Missing from your pages, read it and *I added it*. Both
    # already read shoppers' chats; the Developer never does.
    GAPS: frozenset({OWNER, SUPPORT}),
    # ADR-0068 §4 (R61: A): Shoppers asked for, read it and *Hide*. What to sell
    # is the owner's decision, as Sold out.
    WANTED: frozenset({OWNER}),
}

#: A person's own routes. They come before a shop is chosen, so they name no
#: shop and need no permission: signing in, signing out, and *which shops am I in*.
PERSON_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/v1/console/auth/request-link"),
        ("POST", "/v1/console/auth/verify"),
        ("POST", "/v1/console/auth/sign-out"),
        ("GET", "/v1/console/me"),
        # The invite link: whoever holds it proves the inbox it was sent to,
        # and the shop it names is checked against the link, never trusted.
        ("POST", "/v1/console/auth/accept-invite"),
        # Signing up (ADR-0058 §7): before there is a person or a shop. The
        # link proves the inbox; the shop it makes waits for FiveNeurals.
        ("POST", "/v1/console/auth/sign-up"),
        ("POST", "/v1/console/auth/confirm-sign-up"),
    }
)

_SHOP = "/v1/console/shops/{tenant_id}"
_SELL = "/v1/sell/console/shops/{tenant_id}"

#: Every dashboard route that names a shop, and the permission it needs.
ROUTES: dict[tuple[str, str], str] = {
    # Home: what every member's Home reads beyond their own screens (R12).
    ("GET", f"{_SHOP}/home"): HOME,
    # People: the Owner's alone (ADR-0058 §4).
    ("GET", f"{_SHOP}/people"): PEOPLE,
    ("PUT", f"{_SHOP}/people/{{user_id}}"): PEOPLE,
    ("DELETE", f"{_SHOP}/people/{{user_id}}"): PEOPLE,
    ("POST", f"{_SHOP}/invites"): PEOPLE,
    ("POST", f"{_SHOP}/invites/{{invite_id}}/send-again"): PEOPLE,
    ("DELETE", f"{_SHOP}/invites/{{invite_id}}"): PEOPLE,
    # Review: read and grade (one permission, as the ADR's table has it).
    ("GET", f"{_SHOP}/review/scorecard"): REVIEW,
    ("GET", f"{_SHOP}/review"): REVIEW,
    ("GET", f"{_SHOP}/review/counts"): REVIEW,
    ("GET", f"{_SHOP}/review/{{shadow_id}}"): REVIEW,
    ("POST", f"{_SHOP}/review/{{shadow_id}}/grade"): REVIEW,
    # Conversations.
    ("GET", f"{_SHOP}/conversations"): CONVERSATIONS,
    ("GET", f"{_SHOP}/conversations/{{conversation_id}}"): CONVERSATIONS,
    # Answering a handed-over shopper (ADR-0062 §8): their address, and Mark as
    # answered. Owner and Support only.
    ("GET", f"{_SHOP}/conversations/{{conversation_id}}/waiting"): HANDOVERS,
    ("POST", f"{_SHOP}/conversations/{{conversation_id}}/answered"): HANDOVERS,
    # Shop connection: read, Check, Sync now, the tokens and the sign-in secret.
    ("GET", f"{_SHOP}/store"): CONNECTION,
    ("POST", f"{_SHOP}/store/{{store_id}}/sync"): CONNECTION,
    ("GET", f"{_SHOP}/store/{{store_id}}/health"): CONNECTION,
    ("POST", f"{_SHOP}/token"): CONNECTION,
    ("POST", f"{_SHOP}/checks"): CONNECTION,
    ("GET", f"{_SHOP}/checks/{{check_id}}"): CONNECTION,
    ("POST", f"{_SHOP}/store/{{store_id}}/token"): CONNECTION,
    ("GET", f"{_SHOP}/customer-secret"): CONNECTION,
    ("POST", f"{_SHOP}/customer-secret"): CONNECTION,
    # Shop connection: Connect, and the contact details.
    ("POST", f"{_SHOP}/connect"): CONNECT,
    ("GET", f"{_SHOP}/contact"): CONTACT,
    ("PUT", f"{_SHOP}/contact"): CONTACT,
    # Go live and back to practice.
    ("PUT", f"{_SHOP}/mode"): MODE,
    # Usage and cost.
    ("GET", f"{_SHOP}/usage"): USAGE,
    # Sold out (served by the console, so it names no agent).
    ("GET", f"{_SHOP}/sold-out"): SOLD_OUT,
    # Missing from your pages (ADR-0064; served by the console, so it names no agent).
    ("GET", f"{_SHOP}/gaps"): GAPS,
    ("POST", f"{_SHOP}/gaps/added"): GAPS,
    # Shoppers asked for (ADR-0068; served by the console, so it names no agent).
    ("GET", f"{_SHOP}/wanted"): WANTED,
    ("POST", f"{_SHOP}/wanted/hidden"): WANTED,
    # Suggestions (served by SELL, so it is SELL's own permission).
    ("GET", f"{_SELL}/suggestions"): SUGGESTIONS,
    ("GET", f"{_SELL}/suggestions/catalogue"): SUGGESTIONS,
    ("GET", f"{_SELL}/suggestions/{{product_id}}/preview"): SUGGESTIONS,
    ("PUT", f"{_SELL}/suggestions/{{product_id}}"): SUGGESTIONS,
    ("DELETE", f"{_SELL}/suggestions/{{product_id}}"): SUGGESTIONS,
}


__all__ = [
    "DEVELOPER",
    "GAPS",
    "HANDOVERS",
    "HOME",
    "OWNER",
    "PEOPLE",
    "PERSON_ROUTES",
    "ROLES",
    "ROUTES",
    "SUPPORT",
    "WANTED",
    "WHO",
]

#: The FiveNeurals admin's routes (ADR-0061). Not shop routes: they name no
#: permission, and each must state the admin check on the route (`AdminOnly`),
#: which `tests/unit/test_admin.py` holds. A route added under `/v1/admin` and
#: not here fails that test.
ADMIN_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/v1/admin/shops"),
        ("GET", "/v1/admin/shops/{tenant_id}"),
        ("POST", "/v1/admin/shops/{tenant_id}/approve"),
        ("POST", "/v1/admin/shops/{tenant_id}/refuse"),
        ("GET", "/v1/admin/usage"),
        ("PUT", "/v1/admin/shops/{tenant_id}/switches/{key}"),
        # The code from the admin's phone (ADR-0067): the only admin routes that
        # open before it is typed. They still need a live admin, signed in within
        # 12 hours.
        ("POST", "/v1/admin/code/setup"),
        ("POST", "/v1/admin/code/setup/confirm"),
        ("POST", "/v1/admin/code"),
    }
)

#: The admin routes that work before the phone's code is typed (ADR-0067 §4, §5).
ADMIN_CODE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/v1/admin/code/setup"),
        ("POST", "/v1/admin/code/setup/confirm"),
        ("POST", "/v1/admin/code"),
    }
)
