#!/usr/bin/env python3
"""Create tenants, issue keys, and read what a tenant has used.

    make tenant-new  NAME="Acme Store" AGENTS=care
    make tenant-show TENANT=tn_01J8...
    make key-new     TENANT=tn_01J8... SCOPES=care:chat:write NAME=server
    make key-revoke  TENANT=tn_01J8... KEY=key_01J8...
    make tenant-usage TENANT=tn_01J8...
    make webhook-drain TENANT=tn_01J8...

The operator tool for milestone 1.13. Until the merchant console exists this is
how a tenant comes into being, so it is a real command rather than a paragraph
of SQL in a document that will go stale.

**Two things it does deliberately.**

It connects as the ordinary application role, so every command here runs under
the same Row-Level Security every request does. Creating a tenant works because
the insert is scoped to the id being created; nothing here can read or touch a
tenant it was not given.

It prints a new key exactly once, and says so. There is no command to show a key
again, because the hash is all that is stored — which is the property that makes
a database dump unusable rather than catastrophic.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

from neura_core import Database, configure_logging, load_env, new_id
from neura_core.ids import TENANT
from neura_core.tenancy import (
    ApiKeyKind,
    ApiKeyRepository,
    TenantRepository,
    UsageMeter,
)

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YELLOW = "\033[33m"
OFF = "\033[0m"


async def create_tenant(db: Database, name: str, agents: list[str]) -> int:
    tenant_id = new_id(TENANT)
    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).create(
            tenant_id=tenant_id, name=name, enabled_agents=agents
        )

    print(f"\n  {BOLD}{tenant.tenant_id}{OFF}  {tenant.name}")
    print(f"  {DIM}agents: {', '.join(sorted(tenant.enabled_agents)) or '(none)'}{OFF}\n")
    return 0


async def show_tenant(db: Database, tenant_id: str) -> int:
    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).get(tenant_id)
        if tenant is None:
            print(f"{RED}no such tenant (or it belongs to someone else){OFF}")
            return 1
        api_keys = await ApiKeyRepository(session).list_for(tenant_id)
        totals = await UsageMeter(session).totals(tenant_id)

    print(f"\n  {BOLD}{tenant.name}{OFF}  {DIM}{tenant.tenant_id}{OFF}")
    print(f"  status  {tenant.status.value}")
    print(f"  agents  {', '.join(sorted(tenant.enabled_agents)) or '(none)'}")
    print(f"  config  {tenant.config.model_dump(exclude_none=True)}")
    print(f"\n  {BOLD}keys{OFF}")
    for key in api_keys:
        state = "revoked" if key.revoked_at else "active"
        used = key.last_used_at.strftime("%Y-%m-%d") if key.last_used_at else "never used"
        print(f"    {key.id}  {key.token_prefix}…  {state:<8} {DIM}{used}{OFF}")
    if not api_keys:
        print(f"    {DIM}none — issue one with `make key-new`{OFF}")

    print(f"\n  {BOLD}usage, all time{OFF}")
    print(f"    {totals.turns} turns · {totals.llm_calls} model calls · ${totals.cost_usd}\n")
    return 0


async def issue_key(
    db: Database,
    tenant_id: str,
    *,
    scopes: list[str],
    name: str,
    public: bool,
    origins: list[str],
    expires_days: int | None,
) -> int:
    kind = ApiKeyKind.PUBLIC if public else ApiKeyKind.SECRET
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_days) if expires_days is not None else None
    )

    async with db.tenant_session(tenant_id) as session:
        if await TenantRepository(session).get(tenant_id) is None:
            print(f"{RED}no such tenant{OFF}")
            return 1
        record, issued = await ApiKeyRepository(session).issue(
            tenant_id,
            kind=kind,
            scopes=scopes,
            name=name,
            allowed_origins=origins,
            expires_at=expires_at,
        )

    print(f"\n  {BOLD}{issued.token}{OFF}")
    print(f"  {YELLOW}Copy it now — only its hash is stored, so it cannot be shown again.{OFF}")
    print(f"  {DIM}{record.id} · scopes: {', '.join(sorted(record.scopes)) or '(none)'}{OFF}\n")
    return 0


async def revoke_key(db: Database, tenant_id: str, key_id: str) -> int:
    async with db.tenant_session(tenant_id) as session:
        key = await ApiKeyRepository(session).revoke(key_id)
    print(f"\n  revoked {key.id} ({key.token_prefix}…) at {key.revoked_at}\n")
    return 0


async def show_usage(db: Database, tenant_id: str) -> int:
    async with db.tenant_session(tenant_id) as session:
        meter = UsageMeter(session)
        today = await meter.by_agent(tenant_id)
        spend = await meter.spend_today(tenant_id)

    print(f"\n  {BOLD}today{OFF}  {DIM}{tenant_id}{OFF}")
    if not today:
        print(f"    {DIM}nothing recorded{OFF}\n")
        return 0
    for agent, totals in today.items():
        print(
            f"    {agent:<8} {totals.turns:>5} turns  {totals.llm_calls:>5} calls  "
            f"{totals.total_tokens:>8} tokens  ${totals.cost_usd}"
        )
    print(f"\n    {BOLD}${spend}{OFF} against today's ceiling\n")
    return 0


async def drain_webhooks(tenant_id: str) -> int:
    """Send whatever is queued for one tenant, now.

    The repair for open question **P7**. The drainer finds work through a Redis
    set naming tenants with queued deliveries, because no transaction can ask
    "which deliveries are due?" across tenants — a session that has not named a
    tenant matches no row anywhere (ADR-0008), and the alternatives were a
    ``BYPASSRLS`` role or a policy exemption.

    If that Redis set is lost, the *rows* are safe and the *schedule* is not:
    they wait until the tenant's next event re-registers them. This is the
    command that unsticks them without either of the two exemptions.
    """
    from neura_api.webhooks import WebhookDrainer

    database = Database.from_settings()
    drainer = WebhookDrainer(database, None)
    try:
        await drainer.note(tenant_id)
        sent = await drainer.drain_tenant(tenant_id)
    finally:
        await drainer.stop()
        await database.dispose()

    print(f"\n  delivered {sent} queued event(s) for {tenant_id}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-tenant")
    create.add_argument("--name", required=True)
    create.add_argument("--agents", default="", help="comma-separated agent keys")

    show = commands.add_parser("show")
    show.add_argument("--tenant-id", required=True)

    key = commands.add_parser("issue-key")
    key.add_argument("--tenant-id", required=True)
    key.add_argument("--scopes", default="")
    key.add_argument("--name", default="")
    key.add_argument("--public", action="store_true", help="mint an fn_pk_ widget key")
    key.add_argument("--origins", default="", help="required for --public")
    key.add_argument("--expires-days", type=int, default=None)

    revoke = commands.add_parser("revoke-key")
    revoke.add_argument("--tenant-id", required=True)
    revoke.add_argument("--key-id", required=True)

    usage = commands.add_parser("usage")
    usage.add_argument("--tenant-id", required=True)

    drain = commands.add_parser("drain-webhooks")
    drain.add_argument("--tenant-id", required=True)

    return parser


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def main() -> int:
    load_env()
    configure_logging(level="WARNING")
    args = build_parser().parse_args()

    db = Database.from_settings()
    if not await db.ping():
        print(f"{RED}no database — run `make up` and `make migrate`{OFF}")
        await db.dispose()
        return 1

    try:
        match args.command:
            case "create-tenant":
                return await create_tenant(db, args.name, _split(args.agents))
            case "show":
                return await show_tenant(db, args.tenant_id)
            case "issue-key":
                return await issue_key(
                    db,
                    args.tenant_id,
                    scopes=_split(args.scopes),
                    name=args.name,
                    public=args.public,
                    origins=_split(args.origins),
                    expires_days=args.expires_days,
                )
            case "revoke-key":
                return await revoke_key(db, args.tenant_id, args.key_id)
            case "usage":
                return await show_usage(db, args.tenant_id)
            case "drain-webhooks":
                return await drain_webhooks(args.tenant_id)
            case _:  # pragma: no cover — argparse rejects anything else
                return 2
    finally:
        await db.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
