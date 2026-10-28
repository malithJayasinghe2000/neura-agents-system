"""Roles, and the permissions each one holds. ADR-0058 §1 to §3.

A **permission** opens one thing; a **role** is a named set of them (a hotel's
key cards: a permission is a door, a role is a card type). This map is the whole
decision, and it is code: never data a browser sends and never a prompt
(`AGENTS.md` rule 3). The dashboard hides what a role cannot open, but that is a
convenience; the API's 403 is the rule.

## How a permission is named

``<area>:<thing>:<read|write>``, the way key scopes already are
(``care:chat:write``). The area is an agent, for a screen the agent serves
itself (``sell:suggestions:write``), or a shop-wide area for one the console
serves (``shop``, ``usage``, ``people``). **The console's own screens name no
agent**, Conversations and Review included although they show CARE's and SELL's
chats, because shared code may not learn an agent's name (AGENTS.md; G88).

## Who holds what

* **The Owner holds every permission**, including any an agent brings later
  (R4), so a new agent's screen opens to the Owner without an edit here.
* **Support and the Developer hold exactly the sets below.** An agent that wants
  one of them to open its screen says so in its own ADR, and the set grows then.
* **A role this module does not know holds nothing**, and so does a permission
  that is not well formed. Both are the safe direction: a typo in a role or on a
  route refuses rather than opens. The database refuses an unknown role as well
  (``ck_memberships_role``), so the first should never be seen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum


class Role(StrEnum):
    """The three roles a person can have in one shop (ADR-0058 §2)."""

    OWNER = "owner"
    SUPPORT = "support"
    DEVELOPER = "developer"


#: Conversations: read every chat, CARE's and SELL's.
CONVERSATIONS_READ = "shop:conversations:read"
#: Review: read the held and sent replies, and grade them.
REVIEW_WRITE = "shop:review:write"
#: Sold out: products shoppers kept viewing while they could not be bought.
SOLD_OUT_READ = "shop:sold_out:read"
#: Shop connection: read it, Check, Sync now, the shop token and the sign-in secret.
CONNECTION_WRITE = "shop:connection:write"
#: Shop connection: Connect.
CONNECT_WRITE = "shop:connect:write"
#: Shop connection: the contact details a handed-over shopper is given.
CONTACT_WRITE = "shop:contact:write"
#: *Go live*, and back to practice mode.
MODE_WRITE = "shop:mode:write"
#: Usage and cost.
USAGE_READ = "usage:cost:read"
#: People: invite, change a role, remove.
PEOPLE_WRITE = "people:members:write"
#: Home: what every member's Home reads beyond their own screens (R12): the
#: mode, and for whoever reads chats, how many were handed to a person.
HOME_READ = "shop:home:read"
#: Answer a handed-over shopper (ADR-0062 §8): see the email they left (or the
#: shop's own record of a signed-in one), *Answer by email*, *Mark as answered*.
#: Served by the console for every assistant, so it names no agent (G102).
HANDOVERS_WRITE = "shop:handovers:write"
#: Missing from your pages (ADR-0064 §5): what shoppers asked that the shop's
#: pages do not say, *I added it*, and Home's count. Served by the console for
#: whichever assistant finds them, so it names no agent (G88).
GAPS_WRITE = "shop:gaps:write"
#: Shoppers asked for (ADR-0068 §4, R61): what shoppers asked for that the shop
#: does not sell, *Hide*, Home's count, and *See the chats* (Conversations'
#: ``?wanted=``). The Owner's alone: what to sell is the owner's decision, as
#: Sold out. Named in the ADR; it covers *Hide* too.
WANTED_READ = "shop:wanted:read"

#: The refusal of a member whose role does not include what was asked for. Its
#: own code, so the dashboard can say *"You can't open this page"* rather than a
#: general error, and a test can name it. Here, beside the map, because the
#: people rules refuse with it too.
ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"

#: What each role other than the Owner holds. The Owner holds everything.
ROLE_PERMISSIONS: Mapping[Role, frozenset[str]] = {
    # The help desk: chats, grading, and answering handed-over shoppers
    # (ADR-0058 §8, ADR-0062). Never keys, the connection, Go live, people or money.
    Role.SUPPORT: frozenset(
        {HOME_READ, CONVERSATIONS_READ, REVIEW_WRITE, HANDOVERS_WRITE, GAPS_WRITE}
    ),
    # Whoever builds the bridge: all of Shop connection, the same page as the
    # Owner's (R10, settled at the mockup: B). Never a shopper's chat.
    Role.DEVELOPER: frozenset({HOME_READ, CONNECTION_WRITE, CONNECT_WRITE, CONTACT_WRITE}),
}

_PERMISSION = re.compile(r"^[a-z][a-z_]*:[a-z][a-z_]*:(read|write)$")


def is_permission(name: str) -> bool:
    """Whether ``name`` is a well-formed permission: three lower-case parts, the
    last ``read`` or ``write``. No wildcards: a permission names one door."""
    return bool(_PERMISSION.match(name))


def role_may(role: str, permission: str) -> bool:
    """Does a person with ``role`` hold ``permission``? Checked on every request.

    ``role`` is the membership's column, as read from the database.
    """
    if not is_permission(permission):
        return False
    try:
        known = Role(role)
    except ValueError:
        return False
    if known is Role.OWNER:
        return True
    return permission in ROLE_PERMISSIONS.get(known, frozenset())


__all__ = [
    "CONNECTION_WRITE",
    "CONNECT_WRITE",
    "CONTACT_WRITE",
    "CONVERSATIONS_READ",
    "GAPS_WRITE",
    "HANDOVERS_WRITE",
    "HOME_READ",
    "MODE_WRITE",
    "PEOPLE_WRITE",
    "REVIEW_WRITE",
    "ROLE_NOT_ALLOWED",
    "ROLE_PERMISSIONS",
    "SOLD_OUT_READ",
    "USAGE_READ",
    "WANTED_READ",
    "Role",
    "is_permission",
    "role_may",
]
