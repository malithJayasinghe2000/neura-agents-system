"""The FiveNeurals admin dashboard's routes. ADR-0061.

Five routes under ``/v1/admin``, each behind ``AdminOnly`` (a live admin,
signed in within 12 hours; anyone else gets *No such page*):

* ``GET /shops``: every shop's facts, waiting shops first, with its last 7 days;
* ``GET /shops/{tenant_id}``: one shop's facts;
* ``POST /shops/{tenant_id}/approve``: a waiting shop becomes an ordinary one,
  with the assistants chosen (R14); its Owners get the approval email;
* ``POST /shops/{tenant_id}/refuse``: a waiting shop is removed; its Owners get
  the refusal email and keep their accounts;
* ``GET /usage``: AI use across every shop, per shop and per assistant;
* ``PUT /shops/{tenant_id}/switches/{key}``: one feature of one shop on or off
  (ADR-0065). The switches are read from the discovered agents' manifests, so a
  key is data here, like an assistant's.

**Shop facts only, never a shopper** (§1): every read across shops comes from
``neura_core.identity.admins``, whose two database functions can return nothing
else, and only to an admin's own transaction. Approve, refuse and a switch write
one shop in that shop's own session, as the commands do, with the admin in its
record; a shop's switches are read the same way, after the admin check.

**No agent is named here** (AGENTS.md): the assistants are data, checked against
the agents this API discovered; CARE being the usual start is the dashboard's
default and the command's (R14), not this module's.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.dependencies import AdminActor, AdminOnly, DatabaseDep
from neura_api.envelopes import envelope
from neura_api.routes.console_sign_up import approved_email, refused_email
from neura_core import ConflictError, NotFoundError, ValidationError, get_logger, get_settings
from neura_core.email import Mailer
from neura_core.identity.admins import ShopFacts, UsageFacts, admin_shops, admin_usage
from neura_core.identity.sign_up import approve_shop, waiting_shop
from neura_core.tenancy import TenantConfig, TenantRepository, TurnMode
from neura_core.tenancy.removal import remove_tenant
from neura_core.tenancy.switches import Switch, SwitchRepository
from neura_core.tenancy.usage import today

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

AdminDep = Annotated[AdminActor, Depends(AdminOnly())]

#: The periods offered and the days each looks back, as the Usage screen's.
PERIODS: dict[str, int] = {"today": 0, "7d": 6, "30d": 29}

_COUNTS = ("conversations", "turns", "escalations", "blocked", "llm_calls")


class Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The assistants, as their keys. At least one; the dashboard ticks the
    #: usual one, and the command names its own default.
    agents: list[str] = Field(default_factory=list, max_length=20)


class SetSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool


@router.get("/shops", summary="Every shop's facts, waiting shops first")
async def shops(actor: AdminDep, db: DatabaseDep) -> dict[str, object]:
    day = today()
    async with db.identity_session(actor.user_id) as session:
        facts = await admin_shops(session)
        week = _by_shop(await admin_usage(session, since=day - timedelta(days=6), until=day))
    return envelope(
        {
            "shops": [_shop(shop, week.get(shop.tenant_id)) for shop in facts],
            "waiting": sum(1 for shop in facts if shop.status == "waiting"),
        }
    )


@router.get("/shops/{tenant_id}", summary="One shop's facts")
async def shop(
    tenant_id: str, actor: AdminDep, request: Request, db: DatabaseDep
) -> dict[str, object]:
    day = today()
    async with db.identity_session(actor.user_id) as session:
        found = next((s for s in await admin_shops(session) if s.tenant_id == tenant_id), None)
        if found is None:
            raise NotFoundError("No such shop.", details={"tenant_id": tenant_id})
        week = _by_shop(await admin_usage(session, since=day - timedelta(days=6), until=day))
    async with db.tenant_session(tenant_id) as session:
        records = await SwitchRepository(session).all(tenant_id)
    declared = _declared(request)
    switches = [
        _switch(key, declared[key], records.get(key), actor)
        for key in sorted(declared)
        if declared[key][0] in found.assistants
    ]
    return envelope({"shop": {**_shop(found, week.get(tenant_id)), "switches": switches}})


@router.put("/shops/{tenant_id}/switches/{key}", summary="Switch one feature of a shop on or off")
async def set_switch(
    tenant_id: str,
    key: str,
    body: SetSwitch,
    actor: AdminDep,
    request: Request,
    db: DatabaseDep,
) -> dict[str, object]:
    declared = _declared(request)
    if key not in declared:
        raise ValidationError("No such switch.", code="UNKNOWN_SWITCH", details={"key": key})
    agent = declared[key][0]
    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).get(tenant_id)
        if tenant is None:
            raise NotFoundError("No such shop.", details={"tenant_id": tenant_id})
        if agent not in tenant.enabled_agents:
            raise ValidationError(
                "This shop does not have that assistant.",
                code="NOT_THIS_SHOPS_ASSISTANT",
                details={"key": key},
            )
        switches = SwitchRepository(session)
        changed = await switches.set(tenant_id, key, on=body.on, by=actor.user_id)
        if changed is not None:
            await PostgresAuditLog(session).record(
                AuditEntry(
                    tenant_id=tenant_id,
                    event_type=AuditEvent.CONFIG_CHANGE,
                    actor=actor.user_id,
                    outcome="switch.on" if body.on else "switch.off",
                    payload={"key": key},
                )
            )
        current = changed or await switches.get(tenant_id, key)
    log.info(
        "admin_switch_set", tenant_id=tenant_id, key=key, on=body.on, changed=changed is not None
    )
    return envelope(
        {"changed": changed is not None, "switch": _switch(key, declared[key], current, actor)}
    )


@router.post("/shops/{tenant_id}/approve", summary="Approve a waiting shop")
async def approve(
    tenant_id: str, body: Approve, actor: AdminDep, request: Request, db: DatabaseDep
) -> dict[str, object]:
    chosen = sorted(set(body.agents))
    if not chosen:
        raise ValidationError("Choose at least one assistant.", code="NO_ASSISTANT")
    known = set(getattr(request.app.state, "agents", {}) or {})
    unknown = sorted(set(chosen) - known)
    if unknown:
        raise ValidationError(
            "No such assistant.", code="UNKNOWN_ASSISTANT", details={"unknown": unknown}
        )

    async with db.tenant_session(tenant_id) as session:
        await _exists(session, tenant_id)
        approved = await approve_shop(session, tenant_id, agents=chosen)
        await PostgresAuditLog(session).record(
            AuditEntry(
                tenant_id=tenant_id,
                event_type=AuditEvent.CONFIG_CHANGE,
                actor=actor.user_id,
                outcome="shop.approved",
                payload={"agents": chosen},
            )
        )

    settings = get_settings()
    subject, text = approved_email(shop=approved.name, dashboard=settings.console_base_url)
    emailed = _mail(approved.owners, subject, text, event="shop_approved_mail_not_delivered")
    log.info("admin_shop_approved", tenant_id=tenant_id, by=actor.user_id)
    return envelope(
        {
            "approved": True,
            "tenant_id": tenant_id,
            "name": approved.name,
            "assistants": chosen,
            "owners": list(approved.owners),
            "emailed": emailed,
        }
    )


@router.post("/shops/{tenant_id}/refuse", summary="Refuse a waiting shop: it is removed")
async def refuse(tenant_id: str, actor: AdminDep, db: DatabaseDep) -> dict[str, object]:
    async with db.tenant_session(tenant_id) as session:
        await _exists(session, tenant_id)
        waiting = await waiting_shop(session, tenant_id)
        if waiting is None:
            raise _not_waiting("refused")
        # Recorded before the shop goes: the audit log outlives it (S10).
        await PostgresAuditLog(session).record(
            AuditEntry(
                tenant_id=tenant_id,
                event_type=AuditEvent.CONFIG_CHANGE,
                actor=actor.user_id,
                outcome="shop.refused",
                payload={},
            )
        )
        await remove_tenant(session, tenant_id)

    # After the removal, so the email states what is already true.
    subject, text = refused_email(shop=waiting.name)
    emailed = _mail(waiting.owners, subject, text, event="shop_refused_mail_not_delivered")
    log.info("admin_shop_refused", tenant_id=tenant_id, by=actor.user_id)
    return envelope(
        {
            "refused": True,
            "tenant_id": tenant_id,
            "name": waiting.name,
            "owners": list(waiting.owners),
            "emailed": emailed,
        }
    )


@router.get("/usage", summary="AI use and cost across every shop")
async def usage(
    actor: AdminDep, db: DatabaseDep, period: Annotated[str, Query()] = "30d"
) -> dict[str, object]:
    if period not in PERIODS:
        raise ValidationError(
            "Unknown period.", details={"period": period, "expected": sorted(PERIODS)}
        )
    day = today()
    since = day - timedelta(days=PERIODS[period])
    async with db.identity_session(actor.user_id) as session:
        facts = await admin_shops(session)
        rows = await admin_usage(session, since=since, until=day)

    names = {shop.tenant_id: shop.name for shop in facts}
    by_shop = _by_shop(rows)
    by_agent: dict[str, list[UsageFacts]] = defaultdict(list)
    for row in rows:
        by_agent[row.agent_key].append(row)

    shop_rows = sorted(
        (
            {"tenant_id": tenant_id, "name": names.get(tenant_id), **_counts(totals)}
            for tenant_id, totals in by_shop.items()
        ),
        key=lambda r: (-int(r["llm_calls"]), str(r["name"] or r["tenant_id"])),
    )
    return envelope(
        {
            "period": {
                "key": period,
                "days": PERIODS[period] + 1,
                "from": since.isoformat(),
                "to": day.isoformat(),
            },
            "totals": _counts(rows),
            "by_shop": shop_rows,
            "by_assistant": [
                {"agent_key": agent, **_counts(agent_rows)}
                for agent, agent_rows in sorted(by_agent.items())
            ],
            "shops_without_use": sum(1 for shop in facts if shop.tenant_id not in by_shop),
        }
    )


def _by_shop(rows: list[UsageFacts]) -> dict[str, list[UsageFacts]]:
    grouped: dict[str, list[UsageFacts]] = defaultdict(list)
    for row in rows:
        grouped[row.tenant_id].append(row)
    return dict(grouped)


def _counts(rows: list[UsageFacts]) -> dict[str, Any]:
    """Counts, and a cost said as measured only when something was priced."""
    cost = sum((row.cost_usd for row in rows), Decimal("0"))
    counts: dict[str, Any] = {name: sum(getattr(row, name) for row in rows) for name in _COUNTS}
    counts["total_tokens"] = sum(row.prompt_tokens + row.completion_tokens for row in rows)
    counts["cost"] = _money(cost)
    return counts


def _money(cost: Decimal) -> dict[str, object]:
    # Zero says nothing: a free local model and an unpriced one both record it.
    return {"usd": str(cost.quantize(Decimal("0.000001"))), "measured": cost > 0}


def _shop(shop: ShopFacts, week: list[UsageFacts] | None) -> dict[str, object]:
    rows = week or []
    mode = TenantConfig.model_validate({"mode": shop.mode} if shop.mode else {}).mode
    return {
        "tenant_id": shop.tenant_id,
        "name": shop.name,
        "status": shop.status,
        "mode": "practice" if mode is TurnMode.SHADOW else "live",
        "assistants": list(shop.assistants),
        "website": shop.website,
        "since": shop.created_at.isoformat(),
        "connected": shop.connected,
        "owners": list(shop.owners),
        "chats_7d": sum(row.conversations for row in rows),
        "ai_calls_7d": sum(row.llm_calls for row in rows),
        "cost_7d": _money(sum((row.cost_usd for row in rows), Decimal("0"))),
    }


def _declared(request: Request) -> dict[str, tuple[str, str, str]]:
    """Every switch the discovered agents declare: key to (agent, name, text).

    A key must start with its own agent's key, so one agent cannot declare a
    switch that reads as another's.
    """
    declared: dict[str, tuple[str, str, str]] = {}
    for agent_key, discovered in (getattr(request.app.state, "agents", {}) or {}).items():
        for key, (name, text) in (getattr(discovered.manifest, "switches", None) or {}).items():
            if key.startswith(f"{agent_key}."):
                declared[key] = (agent_key, name, text)
    return declared


def _switch(
    key: str, declared: tuple[str, str, str], record: Switch | None, actor: AdminActor
) -> dict[str, object]:
    agent, name, text = declared
    return {
        "key": key,
        "assistant": agent,
        "name": name,
        "text": text,
        # No record: never changed, so on (ADR-0065 §1).
        "on": record is None or record.on,
        "changed_at": record.changed_at.isoformat() if record else None,
        "changed_by_you": bool(record and record.changed_by == actor.user_id),
    }


async def _exists(session: Any, tenant_id: str) -> None:
    if await TenantRepository(session).get(tenant_id) is None:
        raise NotFoundError("No such shop.", details={"tenant_id": tenant_id})


def _not_waiting(done: str) -> ConflictError:
    return ConflictError(
        f"Only a shop waiting for approval can be {done}. Another admin, or a command, may have "
        "decided first.",
        code="NOT_WAITING",
    )


def _mail(owners: tuple[str, ...], subject: str, body: str, *, event: str) -> bool:
    """Email each Owner. ``True`` only when every one was sent."""
    if not owners:
        return False
    mailer = Mailer(get_settings())
    sent = True
    for owner in owners:
        result = mailer.send(to=owner, subject=subject, body=body)
        if not result.sent:
            sent = False
            log.error(event, skipped=result.skipped, error=result.error)
    return sent
