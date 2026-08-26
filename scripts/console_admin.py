#!/usr/bin/env python3
"""Console accounts, from the command line. ADR-0026.

    make user-new EMAIL=owner@shop.com NAME="Jane" TENANT=tn_...
    make user-show EMAIL=owner@shop.com
    make user-revoke EMAIL=owner@shop.com TENANT=tn_...
    make user-link EMAIL=owner@shop.com

**There is no sign-up page, and that is a decision rather than a gap.** Anyone
who could reach the console's sign-in form would otherwise be able to create an
account for any address they liked. Accounts exist because somebody with
database access put them there; self-serve onboarding, when it arrives, needs
its own design — an invitation flow, not an open form.

That also means this script is the only way a *first* account comes into being,
which is why it is a script and not a seeded migration: a row in a migration
would be a working login credential committed to version control.

``user-link`` prints a sign-in link instead of mailing one — for the case where
SMTP is not configured yet, or mail is not arriving and you need to know whether
the problem is delivery or the login flow itself. It is a **credential printed
to a terminal**, so it says so.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select, update

from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import request_sign_in_link
from neura_core.identity.schema import memberships, users


async def create(email: str, name: str, tenant_id: str) -> int:
    db = Database.from_settings()
    try:
        async with db.identity_session() as session:
            existing = (
                await session.execute(select(users.c.id).where(users.c.email == email))
            ).first()
            if existing:
                user_id = str(existing[0])
                print(f"  user exists   {user_id}  {email}")
            else:
                user_id = ids.new_id(ids.USER)
                await session.execute(users.insert().values(id=user_id, email=email, name=name))
                print(f"  user created  {user_id}  {email}")

        if not tenant_id:
            print("\n  No tenant given, so this person can sign in and act for nobody.")
            print("  Make one with `make tenant-new`, then re-run with TENANT=tn_...\n")
            return 0

        # Tenant-scoped, so this needs a tenant transaction — the policy is the
        # same one that will guard every read the console does later.
        async with db.tenant_session(tenant_id) as session:
            held = (
                await session.execute(
                    select(memberships.c.id, memberships.c.revoked_at).where(
                        memberships.c.tenant_id == tenant_id,
                        memberships.c.user_id == user_id,
                    )
                )
            ).first()
            if held and held[1] is None:
                print(f"  membership    already held for {tenant_id}")
            elif held:
                await session.execute(
                    update(memberships).where(memberships.c.id == held[0]).values(revoked_at=None)
                )
                print(f"  membership    RESTORED for {tenant_id}")
            else:
                await session.execute(
                    memberships.insert().values(
                        id=ids.new_id(ids.MEMBERSHIP),
                        tenant_id=tenant_id,
                        user_id=user_id,
                        role="owner",
                    )
                )
                print(f"  membership    created for {tenant_id}")

        print(f"\n  {email} can now sign in at {get_settings().console_base_url}\n")
        return 0
    finally:
        await db.dispose()


async def show(email: str) -> int:
    db = Database.from_settings()
    try:
        async with db.identity_session() as session:
            row = (
                await session.execute(
                    select(
                        users.c.id, users.c.name, users.c.created_at, users.c.last_seen_at
                    ).where(users.c.email == email)
                )
            ).first()
        if row is None:
            print(f"  no account for {email}")
            return 1

        user_id = str(row[0])
        print(f"\n  {email}")
        print(f"    id          {user_id}")
        print(f"    name        {row[1] or '(none)'}")
        print(f"    created     {row[2]}")
        print(f"    last seen   {row[3] or 'never'}")

        # `app.user_id` is what the `membership_lookup` policy reads. Without it
        # this returns nothing — which would print "no merchants" for a person
        # who has several, so the session is opened deliberately with the id.
        async with db.identity_session(user_id) as session:
            held = (
                await session.execute(
                    select(
                        memberships.c.tenant_id, memberships.c.role, memberships.c.revoked_at
                    ).where(memberships.c.user_id == user_id)
                )
            ).all()

        print("    merchants  ", "none" if not held else "")
        for tenant_id, role, revoked in held:
            state = f"REVOKED {revoked:%Y-%m-%d}" if revoked else role
            print(f"      {tenant_id}  {state}")
        print()
        return 0
    finally:
        await db.dispose()


async def revoke(email: str, tenant_id: str) -> int:
    db = Database.from_settings()
    try:
        async with db.identity_session() as session:
            row = (await session.execute(select(users.c.id).where(users.c.email == email))).first()
        if row is None:
            print(f"  no account for {email}")
            return 1

        async with db.tenant_session(tenant_id) as session:
            result = await session.execute(
                update(memberships)
                .where(
                    memberships.c.tenant_id == tenant_id,
                    memberships.c.user_id == str(row[0]),
                    memberships.c.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )

        if result.rowcount:
            # Not a delete: who *used* to have access is exactly what an
            # incident asks, and a deleted row cannot answer it.
            print(f"  revoked — {email} can no longer act for {tenant_id}")
            print("  Takes effect on their next request; the session cookie is not recalled.")
        else:
            print(f"  nothing to revoke — {email} holds no live membership for {tenant_id}")
        return 0
    finally:
        await db.dispose()


async def link(email: str) -> int:
    db = Database.from_settings()
    try:
        async with db.identity_session() as session:
            minted = await request_sign_in_link(
                session, email=email, console_base_url=get_settings().console_base_url
            )
        if not minted.minted:
            print(f"  no account for {email} — nothing minted")
            return 1

        print("\n  ⚠ This link signs that person in. Treat it as a password.\n")
        print(f"  {minted.url}\n")
        print("  Works once, expires in 15 minutes.\n")
        return 0
    finally:
        await db.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("create", help="Create an account and grant it a merchant")
    new.add_argument("--email", required=True)
    new.add_argument("--name", default="")
    new.add_argument("--tenant", default="")

    shown = sub.add_parser("show", help="An account and the merchants it may act for")
    shown.add_argument("--email", required=True)

    gone = sub.add_parser("revoke", help="Withdraw access to one merchant")
    gone.add_argument("--email", required=True)
    gone.add_argument("--tenant", required=True)

    printed = sub.add_parser("link", help="Print a sign-in link instead of mailing it")
    printed.add_argument("--email", required=True)

    args = parser.parse_args()
    load_env()

    match args.command:
        case "create":
            sys.exit(asyncio.run(create(args.email, args.name, args.tenant)))
        case "show":
            sys.exit(asyncio.run(show(args.email)))
        case "revoke":
            sys.exit(asyncio.run(revoke(args.email, args.tenant)))
        case "link":
            sys.exit(asyncio.run(link(args.email)))


if __name__ == "__main__":
    main()
