"""A new shop signs up, and waits for FiveNeurals. ADR-0058 §7, R14 to R17.

The flow, and what each step is for:

1. **Someone fills in the form** (an email, the shop's name, its website). A
   request is stored with the link's **hash** only, for 15 minutes, and a link
   is mailed. Nothing else is made: no account and no shop. The answer is the
   same for every email, and **every** email gets a link, because someone who
   already has an account may add a second shop (R15). So the form says nothing
   about who has an account.
2. **They click the link.** One transaction deletes the request (so the link
   works once), makes the account when the email has none, makes the shop
   **waiting** for approval, with no assistant and in practice mode, and makes
   them its Owner. The caller then signs them in.
3. **A waiting shop opens nothing** (``TenantStatus.WAITING``): the dashboard
   refuses every shop route but the waiting screen, a key cannot be issued for
   it, and a key would be refused anyway because it is not servable.
4. **FiveNeurals approves it** (``approve_shop``, by command until the admin
   dashboard exists, R8) with the assistants it chooses (R14), or refuses it,
   and the shop is removed.

## Why the email never repeats what was typed

The form is open to anyone, and so is the address it mails. A link that carried
the shop's name would let anyone make NEURA send any text they like to any
inbox. The confirm email says only that someone asked (the route's words).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import ids
from neura_core.errors import ConflictError, ValidationError
from neura_core.identity.login import fingerprint
from neura_core.identity.roles import Role
from neura_core.identity.schema import memberships, sign_up_requests, users
from neura_core.logging import get_logger
from neura_core.tenancy.models import TenantConfig, TenantStatus
from neura_core.tenancy.modes import TurnMode
from neura_core.tenancy.repository import TenantRepository
from neura_core.tenancy.schema import tenants

log = get_logger(__name__)

#: How long a sign-up link works: the same as a sign-in link, because for an
#: existing account it signs them in (R15).
SIGN_UP_TTL = timedelta(minutes=15)

#: The longest shop name and website the form accepts.
SHOP_NAME_MAX = 100
WEBSITE_MAX = 255

#: The refusal of every shop route for a shop waiting for approval. Its own
#: code, so the dashboard can tell it from a role's refusal.
SHOP_WAITING = "SHOP_WAITING"
WAITING_MESSAGE = "This shop is waiting for approval. Nothing opens until FiveNeurals approves it."

_ENTROPY_BYTES = 32
_REQUESTS = sign_up_requests.c
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def shop_name(value: str) -> str:
    """The shop's name with its spaces tidied, or a plain refusal (R17)."""
    name = " ".join(value.split())
    if not name or len(name) > SHOP_NAME_MAX or not name.isprintable():
        raise ValidationError(
            f"Enter your shop's name, up to {SHOP_NAME_MAX} characters.",
            code="INVALID_SHOP_NAME",
        )
    return name


def shop_website(value: str) -> str:
    """A web address, typed with or without ``https://`` (R17 d), or a plain refusal.

    Kept as ``scheme://host[:port][/path]``: the host lower-cased, the query and
    the fragment dropped (they are not the shop, and a tracking code is not
    worth keeping). Only ``http`` and ``https``, a host with at least two parts,
    and no user name or password in it.
    """
    typed = value.strip()
    if not typed or len(typed) > WEBSITE_MAX or any(c.isspace() for c in typed):
        raise _not_a_website()
    if "://" not in typed:
        typed = f"https://{typed}"
    try:
        parts = urlsplit(typed)
        port = parts.port
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise _not_a_website() from None
    labels = host.split(".")
    if (
        parts.scheme.lower() not in {"http", "https"}
        or parts.username is not None
        or parts.password is not None
        or len(labels) < 2
        or not all(_LABEL.match(label) for label in labels)
    ):
        raise _not_a_website()
    kept = f"{parts.scheme.lower()}://{host}{f':{port}' if port else ''}{parts.path.rstrip('/')}"
    if len(kept) > WEBSITE_MAX:
        raise _not_a_website()
    return kept


def _not_a_website() -> ValidationError:
    return ValidationError("Enter your shop's website, like yourshop.com.", code="INVALID_WEBSITE")


@dataclass(frozen=True, slots=True)
class SignUpLink:
    """The link to mail. ``token`` and ``url`` exist only to be emailed: never
    stored, never logged, never returned to a browser."""

    token: str
    url: str


@dataclass(frozen=True, slots=True)
class SignedUp:
    """What a used sign-up link made."""

    user_id: str
    tenant_id: str
    #: The email had no account, and one was made.
    made_account: bool


@dataclass(frozen=True, slots=True)
class WaitingShop:
    """A shop waiting for approval, as FiveNeurals reads it before deciding."""

    tenant_id: str
    name: str
    website: str | None
    signed_up_at: datetime | None
    #: Its Owners' emails: who the approval or refusal email goes to.
    owners: tuple[str, ...]


async def request_sign_up(
    session: AsyncSession,
    *,
    email: str,
    name: str,
    website: str,
    console_base_url: str,
    requested_ip: str = "",
    now: datetime | None = None,
) -> SignUpLink:
    """Store a sign-up request and return its link. Makes nothing else.

    Runs in an :meth:`~neura_core.db.Database.identity_session` with no user: the
    person has proved nothing yet. A second request for the same email replaces
    the first, so the first link stops. Expired requests of anyone are deleted
    here, so the table holds only links in flight.
    """
    moment = now or datetime.now(UTC)
    name = shop_name(name)
    address = shop_website(website)
    token = secrets.token_urlsafe(_ENTROPY_BYTES)

    await session.execute(delete(sign_up_requests).where(_REQUESTS.expires_at <= moment))
    statement = pg_insert(sign_up_requests).values(
        id=ids.new_id(ids.SIGN_UP),
        email=email,
        shop_name=name,
        website=address,
        token_hash=fingerprint(token),
        expires_at=moment + SIGN_UP_TTL,
        requested_ip=requested_ip,
        created_at=moment,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[_REQUESTS.email],
            set_={
                column: statement.excluded[column]
                for column in (
                    "id",
                    "shop_name",
                    "website",
                    "token_hash",
                    "expires_at",
                    "requested_ip",
                    "created_at",
                )
            },
        )
    )
    # No email in the line: the address alone is enough to trace a burst.
    log.info("sign_up_link_minted", ip=requested_ip)
    query = urlencode({"token": token})
    return SignUpLink(token=token, url=f"{console_base_url.rstrip('/')}/auth/sign-up?{query}")


async def confirm_sign_up(
    session: AsyncSession,
    *,
    tenant_id: str,
    token: str,
    now: datetime | None = None,
) -> SignedUp | None:
    """Use a sign-up link: the account, the waiting shop and its Owner, at once.

    ``session`` is a :meth:`~neura_core.db.Database.tenant_session` for
    ``tenant_id``, a **new** shop id, so the shop and its membership pass the
    policy's ``WITH CHECK``. ``users`` and ``sign_up_requests`` carry no tenant
    and are written in the same transaction.

    ``None`` for every kind of failure alike: unknown, used, replaced or run
    out. Deleting the request in the statement that finds it is what makes the
    link work once: two clicks racing, and the second finds nothing.
    """
    if not token:
        return None
    moment = now or datetime.now(UTC)

    used = (
        await session.execute(
            delete(sign_up_requests)
            .where(_REQUESTS.token_hash == fingerprint(token), _REQUESTS.expires_at > moment)
            .returning(_REQUESTS.email, _REQUESTS.shop_name, _REQUESTS.website)
        )
    ).first()
    if used is None:
        log.info("sign_up_token_rejected")
        return None

    made = (
        await session.execute(
            pg_insert(users)
            .values(id=ids.new_id(ids.USER), email=used.email, name="", last_seen_at=moment)
            .on_conflict_do_nothing(index_elements=[users.c.email])
            .returning(users.c.id)
        )
    ).first()
    if made:
        user_id = str(made[0])
    else:
        user_id = str(await session.scalar(select(users.c.id).where(users.c.email == used.email)))
        await session.execute(
            update(users).where(users.c.id == user_id).values(last_seen_at=moment)
        )

    # Practice mode, as every shop starts (ADR-0054 §4); no assistant until
    # FiveNeurals chooses them at approval (R14).
    await TenantRepository(session).create(
        tenant_id=tenant_id,
        name=str(used.shop_name),
        website=str(used.website),
        status=TenantStatus.WAITING,
        config=TenantConfig(mode=TurnMode.SHADOW),
    )
    await session.execute(
        memberships.insert().values(
            id=ids.new_id(ids.MEMBERSHIP),
            tenant_id=tenant_id,
            user_id=user_id,
            role=Role.OWNER.value,
            created_at=moment,
        )
    )
    log.info("sign_up_confirmed", tenant_id=tenant_id, user_id=user_id)
    return SignedUp(user_id=user_id, tenant_id=tenant_id, made_account=bool(made))


async def waiting_tenant_ids(session: AsyncSession) -> list[str]:
    """Every shop waiting for approval, the oldest first: ids and nothing else.

    Through ``neura_waiting_tenants()``, the one statement that may look across
    shops for this (the ADR-0022 pattern): any session can call it, and it
    answers ids only. Each shop is then read in its own tenant session.
    """
    rows = await session.execute(text("SELECT tenant_id FROM neura_waiting_tenants()"))
    return [str(tenant_id) for tenant_id in rows.scalars()]


async def waiting_shop(session: AsyncSession, tenant_id: str) -> WaitingShop | None:
    """The shop, when it is waiting for approval; ``None`` otherwise.

    ``session`` is that shop's own tenant session.
    """
    shop = await TenantRepository(session).get(tenant_id)
    if shop is None or shop.status is not TenantStatus.WAITING:
        return None
    owners = (
        await session.execute(
            select(users.c.email)
            .select_from(memberships.join(users, users.c.id == memberships.c.user_id))
            .where(
                memberships.c.tenant_id == tenant_id,
                memberships.c.role == Role.OWNER.value,
                memberships.c.revoked_at.is_(None),
            )
            .order_by(memberships.c.created_at)
        )
    ).scalars()
    return WaitingShop(
        tenant_id=tenant_id,
        name=shop.name,
        website=shop.website,
        signed_up_at=shop.created_at,
        owners=tuple(str(email) for email in owners),
    )


async def approve_shop(
    session: AsyncSession, tenant_id: str, *, agents: Sequence[str]
) -> WaitingShop:
    """Make a waiting shop an ordinary one, with ``agents`` (R14).

    It keeps practice mode and the daily spending limit every shop has. Refused
    for a shop that is not waiting, so a typo cannot change a live shop's
    assistants.
    """
    shop = await waiting_shop(session, tenant_id)
    if shop is None:
        raise ConflictError("Only a shop waiting for approval can be approved.", code="NOT_WAITING")
    await session.execute(
        update(tenants)
        .where(tenants.c.tenant_id == tenant_id, tenants.c.status == TenantStatus.WAITING.value)
        .values(
            status=TenantStatus.ACTIVE.value,
            enabled_agents=sorted(set(agents)),
            updated_at=func.now(),
        )
    )
    log.info("shop_approved", tenant_id=tenant_id, agents=sorted(set(agents)))
    return shop


__all__ = [
    "SHOP_NAME_MAX",
    "SHOP_WAITING",
    "SIGN_UP_TTL",
    "WAITING_MESSAGE",
    "WEBSITE_MAX",
    "SignUpLink",
    "SignedUp",
    "WaitingShop",
    "approve_shop",
    "confirm_sign_up",
    "request_sign_up",
    "shop_name",
    "shop_website",
    "waiting_shop",
    "waiting_tenant_ids",
]
