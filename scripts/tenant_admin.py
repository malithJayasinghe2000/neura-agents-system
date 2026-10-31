#!/usr/bin/env python3
"""Create tenants, issue keys, and read what a tenant has used.

    make tenant-new  NAME="Acme Store" AGENTS=care
    make tenant-show TENANT=tn_01J8...
    make key-new     TENANT=tn_01J8... SCOPES=care:chat:write NAME=server
    make key-revoke  TENANT=tn_01J8... KEY=key_01J8...
    make tenant-usage TENANT=tn_01J8...
    make webhook-drain TENANT=tn_01J8...
    make tenant-dpa  TENANT=tn_01J8... [WITHDRAW=1]
    make retention-sweep TENANT=tn_01J8...
    make tenant-waiting
    make tenant-approve TENANT=tn_01J8... [AGENTS=care,sell]
    make tenant-refuse  TENANT=tn_01J8...

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

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.jobs.daily import book_daily_jobs
from neura_core import (
    ConfigurationError,
    ConflictError,
    Database,
    Settings,
    configure_logging,
    get_settings,
    load_env,
    new_id,
)
from neura_core.email import Mailer
from neura_core.identity.sign_up import (
    approve_shop,
    waiting_shop,
    waiting_tenant_ids,
)
from neura_core.ids import TENANT
from neura_core.observation import OBSERVE_WRITE, ObservedEventRepository
from neura_core.tenancy import (
    ApiKeyKind,
    ApiKeyRepository,
    TenantConfig,
    TenantRepository,
    TurnMode,
    UsageMeter,
)
from neura_core.tenancy.removal import remove_tenant

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YELLOW = "\033[33m"
OFF = "\033[0m"


async def create_tenant(db: Database, name: str, agents: list[str]) -> int:
    """A new shop starts in practice mode (ADR-0054 §4): no shopper reads a reply
    until the owner presses *Go live* on Home. Written into this shop's settings
    rather than made the model's default, which also decides the mode of a shop
    whose settings never named one."""
    tenant_id = new_id(TENANT)
    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).create(
            tenant_id=tenant_id,
            name=name,
            enabled_agents=agents,
            config=TenantConfig(mode=TurnMode.SHADOW),
        )

    print(f"\n  {BOLD}{tenant.tenant_id}{OFF}  {tenant.name}")
    print(f"  {DIM}agents: {', '.join(sorted(tenant.enabled_agents)) or '(none)'}{OFF}")
    print(f"  {DIM}practice mode: no shopper sees a reply until the owner presses Go live{OFF}\n")
    return 0


async def show_tenant(db: Database, tenant_id: str) -> int:
    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).get(tenant_id)
        if tenant is None:
            print(f"{RED}no such tenant (or it belongs to someone else){OFF}")
            return 1
        api_keys = await ApiKeyRepository(session).list_for(tenant_id)
        totals = await UsageMeter(session).totals(tenant_id)
        held = await ObservedEventRepository(session).count_for(tenant_id)

    print(f"\n  {BOLD}{tenant.name}{OFF}  {DIM}{tenant.tenant_id}{OFF}")
    print(f"  status  {tenant.status.value}")
    print(f"  agents  {', '.join(sorted(tenant.enabled_agents)) or '(none)'}")
    print(f"  config  {tenant.config.model_dump(exclude_none=True)}")
    agreement = (
        f"recorded {tenant.dpa_signed_at:%Y-%m-%d}"
        if tenant.dpa_signed_at
        else "none — nothing about its shoppers may be stored"
    )
    print(f"  dpa     {agreement}")
    print(f"  observed events held  {held}")
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
        try:
            record, issued = await ApiKeyRepository(session).issue(
                tenant_id,
                kind=kind,
                scopes=scopes,
                name=name,
                allowed_origins=origins,
                expires_at=expires_at,
            )
        except ConfigurationError as refused:
            print(f"{RED}refused: {refused.message}{OFF}")
            return 1

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

    **This used to be the repair for a lost schedule; it is now a way to skip
    the wait.** Until 2026-08-26 the drainer found work through a Redis set, and
    losing that set stranded undelivered rows until the tenant's next event
    re-registered them — the cost recorded as open question **P7**. The schedule
    now lives in ``job_queue``, in the same transaction as the deliveries
    (ADR-0022), so there is no index left to lose.

    What remains useful is impatience: a delivery inside its backoff, or a
    merchant who has just fixed their endpoint and would rather not wait out the
    ladder. Nothing here bypasses Row-Level Security — the tenant is named on
    the command line, which is the one thing a background sweep cannot do.
    """
    from neura_api.webhooks import WebhookDrainer

    database = Database.from_settings()
    drainer = WebhookDrainer(database)
    try:
        sent = await drainer.drain_tenant(tenant_id)
    finally:
        await drainer.aclose()
        await database.dispose()

    print(f"\n  delivered {sent} queued event(s) for {tenant_id}\n")
    return 0


async def record_dpa(db: Database, tenant_id: str, *, withdraw: bool) -> int:
    """Record a data-processing agreement, or withdraw one (ADR-0042 §2).

    **Withdrawing deletes, in the same transaction.** Without an agreement there
    is no reason to hold a shopper's events, so they go now rather than at the
    end of their retention period — ADR-0042 §3's *removal on resolution*. The
    key that sent them keeps its scope, and the route refuses it from this
    moment, because the route checks the agreement on every request.
    """
    async with db.tenant_session(tenant_id) as session:
        tenants = TenantRepository(session)
        if await tenants.get(tenant_id) is None:
            print(f"{RED}no such tenant{OFF}")
            return 1
        tenant = await tenants.set_dpa_signed_at(tenant_id, None if withdraw else datetime.now(UTC))
        deleted = await ObservedEventRepository(session).delete_all(tenant_id) if withdraw else 0

    if withdraw:
        print(f"\n  agreement withdrawn for {tenant_id}")
        print(f"  deleted {deleted} observed event(s) — nothing about its shoppers is held\n")
    else:
        print(
            f"\n  agreement recorded for {tenant_id} at {tenant.dpa_signed_at:%Y-%m-%d %H:%M} UTC"
        )
        print(
            f"  {DIM}an `{OBSERVE_WRITE}` key may now be issued: make key-new TENANT={tenant_id} "
        )
        print(f"  SCOPES={OBSERVE_WRITE} NAME=observe{OFF}\n")
    return 0


async def retention_sweep(db: Database, tenant_id: str) -> int:
    """Run one retention pass for a tenant now, and make sure the next is booked.

    The same function the ``retention.sweep`` job runs. Useful for two things:
    proving deletion works without waiting a day, and booking a sweep for a
    tenant whose data predates the job — every *new* write books one, but rows
    written before 2026-09-26 had nothing to book it.
    """
    from neura_api.jobs.retention import enqueue_sweep, sweep

    async with db.tenant_session(tenant_id) as session:
        result = await sweep(session, tenant_id, now=datetime.now(UTC), settings=get_settings())
        if result.remaining:
            job = await enqueue_sweep(session, tenant_id)

    print(f"\n  {result.summary()}")
    if result.remaining:
        print(f"  {DIM}next sweep {job.id} at {job.run_after:%Y-%m-%d %H:%M} UTC{OFF}")
    print()
    return 0


#: Who an audit entry names when FiveNeurals, by this command, acted.
OPERATOR = "tenant_admin"

#: The assistant an approved shop gets when none is named (R14, the owner: A).
DEFAULT_AGENTS = ["care"]


async def list_waiting(db: Database) -> int:
    """Every shop waiting for approval, the oldest first (ADR-0058 §7, AD1)."""
    async with db.identity_session() as session:
        waiting = await waiting_tenant_ids(session)
    if not waiting:
        print(f"\n  {DIM}no shop is waiting for approval{OFF}\n")
        return 0
    print()
    for tenant_id in waiting:
        async with db.tenant_session(tenant_id) as session:
            shop = await waiting_shop(session, tenant_id)
        if shop is None:  # approved or refused a moment ago
            continue
        signed_up = f"{shop.signed_up_at:%Y-%m-%d %H:%M} UTC" if shop.signed_up_at else "?"
        print(f"  {BOLD}{shop.name}{OFF}  {DIM}{tenant_id}{OFF}")
        print(f"    website    {shop.website or '(none)'}")
        print(f"    owner      {', '.join(shop.owners) or '(none)'}")
        print(f"    signed up  {signed_up}\n")
    print(
        f"  {DIM}make tenant-approve TENANT=... [AGENTS=care,sell]   or   make tenant-refuse TENANT=...{OFF}\n"
    )
    return 0


async def approve(db: Database, tenant_id: str, agents: list[str]) -> int:
    """Make a waiting shop an ordinary one, with the assistants named (R14).

    CARE when none is named. It keeps practice mode and the daily spending
    limit every shop has. Its Owners get the approval email (R17).
    """
    from neura_api.registry import discover_agents
    from neura_api.routes.console_sign_up import approved_email

    chosen = sorted(set(agents or DEFAULT_AGENTS))
    unknown = sorted(set(chosen) - set(discover_agents()))
    if unknown:
        print(f"{RED}no such assistant: {', '.join(unknown)} (nothing changed){OFF}")
        return 1

    async with db.tenant_session(tenant_id) as session:
        try:
            shop = await approve_shop(session, tenant_id, agents=chosen)
        except ConflictError:
            print(f"{RED}{tenant_id} is not waiting for approval: nothing changed{OFF}")
            return 1
        # As the admin dashboard does: the daily jobs of its assistants, from now
        # (GROW's night run reaches a shop with no chats, ADR-0072 §8).
        await book_daily_jobs(session, tenant_id)
        await PostgresAuditLog(session).record(
            AuditEntry(
                tenant_id=tenant_id,
                event_type=AuditEvent.CONFIG_CHANGE,
                actor=OPERATOR,
                outcome="shop.approved",
                payload={"agents": chosen},
            )
        )

    print(f"\n  {BOLD}{shop.name}{OFF} approved  {DIM}{tenant_id}{OFF}")
    print(f"  {DIM}assistants: {', '.join(chosen)} · practice mode{OFF}")
    settings = get_settings()
    subject, body = approved_email(shop=shop.name, dashboard=settings.console_base_url)
    _mail(settings, shop.owners, subject, body)
    return 0


async def refuse(db: Database, tenant_id: str) -> int:
    """Remove a waiting shop, then tell its Owners (R16, R17).

    Removed first, from every table that holds its rows (``remove_tenant``, as
    the admin dashboard does), so the email states what is already true. The person keeps their account: they may be in another shop.
    The shop's audit entries stay, as for every removed shop (S10).
    """
    from neura_api.routes.console_sign_up import refused_email

    async with db.tenant_session(tenant_id) as session:
        shop = await waiting_shop(session, tenant_id)
        if shop is None:
            print(f"{RED}{tenant_id} is not waiting for approval: nothing removed{OFF}")
            return 1
        await PostgresAuditLog(session).record(
            AuditEntry(
                tenant_id=tenant_id,
                event_type=AuditEvent.CONFIG_CHANGE,
                actor=OPERATOR,
                outcome="shop.refused",
                payload={},
            )
        )
        # The same removal the admin dashboard uses (ADR-0061 §6): every table
        # holding the shop's rows, read from the database, the audit log kept.
        await remove_tenant(session, tenant_id)

    print(f"\n  {BOLD}{shop.name}{OFF} refused and removed  {DIM}{tenant_id}{OFF}")
    subject, body = refused_email(shop=shop.name)
    _mail(get_settings(), shop.owners, subject, body)
    return 0


def _mail(settings: Settings, owners: tuple[str, ...], subject: str, body: str) -> None:
    """Email each Owner, and say plainly which were not sent."""
    mailer = Mailer(settings)
    for owner in owners:
        result = mailer.send(to=owner, subject=subject, body=body)
        if result.sent:
            print(f"  {DIM}emailed {owner}{OFF}")
        else:
            reason = "email is off (SMTP_HOST is empty)" if result.skipped else result.error
            print(f"  {YELLOW}NOT emailed {owner}: {reason}{OFF}")
    print()


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

    dpa = commands.add_parser("dpa")
    dpa.add_argument("--tenant-id", required=True)
    dpa.add_argument("--withdraw", action="store_true")

    sweep = commands.add_parser("sweep")
    sweep.add_argument("--tenant-id", required=True)

    commands.add_parser("waiting")

    approval = commands.add_parser("approve")
    approval.add_argument("--tenant-id", required=True)
    approval.add_argument("--agents", default="", help="comma-separated; care when empty")

    refusal = commands.add_parser("refuse")
    refusal.add_argument("--tenant-id", required=True)

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
            case "dpa":
                return await record_dpa(db, args.tenant_id, withdraw=args.withdraw)
            case "sweep":
                return await retention_sweep(db, args.tenant_id)
            case "waiting":
                return await list_waiting(db)
            case "approve":
                return await approve(db, args.tenant_id, _split(args.agents))
            case "refuse":
                return await refuse(db, args.tenant_id)
            case _:  # pragma: no cover — argparse rejects anything else
                return 2
    finally:
        await db.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
