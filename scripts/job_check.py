#!/usr/bin/env python3
"""Schedule a real sync, for a tenant the worker was never told about.

    make job-check URL=http://your-shop/neura/v1 TOKEN=xxx

This is the demonstration of open question **P7**, and it is deliberately the
case that was *impossible* before ADR-0022. Under ADR-0008 no transaction can
enumerate tenants, so a background worker could not ask whose catalogue was due
— which is why sync persistence landed on 2026-08-16 with a durable catalogue
and nothing to schedule a crawl of it.

**Two processes, and the split is the whole point.**

* ``--worker`` starts a :class:`JobRunner` and nothing else. It is given a
  database URL. It holds no tenant list, no store credentials, and no
  configuration for any merchant. It is started *first*, before the tenant in
  this run exists.
* The default run then creates a **brand-new tenant** with a fresh id, registers
  the real shop against it, and enqueues one ``sync.store`` job — in a separate
  OS process the worker cannot see.

The worker discovers that tenant through ``neura_due_tenants()``, opens a scoped
session for it, decrypts its store credentials, and crawls the shop. Nothing
tells it the tenant exists.

**Read the first check carefully.** Before the tenant is created, the worker's
own dispatch call must name *nobody*. A run that reported a successful sync
without that line having been empty would prove nothing — it would be consistent
with a worker that had been handed the tenant all along.

**The second act is the outbox.** The webhook drainer had its own five-second
poll over a Redis set until 2026-08-26; it is a job now. This starts a real HTTP
endpoint on this machine, registers it as a merchant would, queues an event, and
watches the same worker deliver a **signed** POST to it — verified here with the
same HMAC a merchant would use. That whole path had never run end to end: the
old drainer was driven by an index no test could produce.

Nothing is written to the shop. Every operation against it is a read.
No models are called: this touches no agent, no graph and no LLM.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import text

from neura_api.jobs import (
    SYNC_STORE,
    WEBHOOK_DRAIN,
    JobRunner,
    SyncStoreHandler,
    WebhookDrainHandler,
    enqueue_drain,
    enqueue_sync,
)
from neura_api.stores import StoreDirectory
from neura_api.webhooks import WebhookDrainer
from neura_commerce.sync import SYNCED_TYPES, DatabaseEntityStore
from neura_core import Database, configure_logging, new_id
from neura_core.ids import TENANT
from neura_core.jobs import JobQueue, JobStatus, due_tenants
from neura_core.tenancy import StoreConnectionRepository, TenantRepository
from neura_core.webhooks import PendingEvent, WebhookEvent, WebhookRepository
from neura_core.webhooks.signing import (
    EVENT_TYPE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    matches,
)

#: How long the demo waits for the worker to notice and finish. A real catalogue
#: crawl at ten requests a second takes a few seconds; the ceiling is here so a
#: broken run *fails* rather than hanging in CI.
TIMEOUT_S = 180.0

#: The worker's poll interval for this demo. The deployed default is five
#: seconds; one keeps the demonstration short without changing what is proved.
DEMO_POLL_S = 1.0


def tick(ok: bool) -> str:
    return "\033[32m✔\033[0m" if ok else "\033[31m✘\033[0m"


def dim(text_: str) -> str:
    return f"\033[2m{text_}\033[0m"


async def _drain(stream: asyncio.StreamReader, into: list[str]) -> None:
    """Keep reading the worker's output, and keep the tail of it.

    Not optional. A pipe nobody reads fills at 64KB and then *blocks the worker
    mid-write* — which would present here as a job that never finishes, i.e. as
    a failure of the thing being demonstrated. It is also what makes a genuine
    failure legible: the first run of this script reported a timeout, and the
    reason (the shop's own database was down) was sitting unread in this pipe.
    """
    while True:
        line = await stream.readline()
        if not line:
            return
        into.append(line.decode(errors="replace").rstrip())
        del into[:-40]


async def run_worker(poll_interval_s: float) -> int:
    """A worker process. Told a database and nothing else."""
    db = Database.from_settings()
    if not await db.ping():
        print("worker: no database at DATABASE_URL", file=sys.stderr)
        return 1

    drainer = WebhookDrainer(db)
    runner = JobRunner(db, poll_interval_s=poll_interval_s)
    runner.register(SYNC_STORE, SyncStoreHandler(StoreDirectory(db)))
    runner.register(WEBHOOK_DRAIN, WebhookDrainHandler(drainer))
    print(f"worker: up, handling {sorted(runner.kinds)}, knowing no tenants", flush=True)

    runner.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.stop()
        await drainer.aclose()
        await db.dispose()
    return 0


class Merchant:
    """A merchant's webhook endpoint, on this machine, answering for real.

    Minimal on purpose — one POST, one 200 — because what is being proved is our
    side of the wire. It keeps the raw body byte for byte, since re-serialising
    parsed JSON before verifying is the classic way to make a correct signature
    look broken.
    """

    def __init__(self) -> None:
        self.received: list[tuple[dict[str, str], bytes]] = []
        self._server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hooks"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            headers = {}
            for line in head.decode("latin-1").split("\r\n")[1:]:
                if ":" in line:
                    name, _, value = line.partition(":")
                    headers[name.strip().lower()] = value.strip()
            length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(length) if length else b""
            self.received.append((headers, body))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            await writer.drain()
        except Exception:  # a merchant's endpoint misbehaving is not our failure
            pass
        finally:
            writer.close()


async def provision(db: Database, tenant_id: str, url: str, token: str) -> str:
    """Create the tenant and register the shop. One transaction, scoped to it."""
    async with db.tenant_session(tenant_id) as session:
        await TenantRepository(session).create(
            name="P7 scheduling probe", tenant_id=tenant_id, enabled_agents=["care"]
        )
        return await StoreConnectionRepository(session).connect(
            tenant_id, platform="generic", base_url=url, credentials={"token": token}
        )


async def forget(db: Database, tenant_id: str) -> None:
    """Remove everything this run created. Runs under RLS as the app role."""
    async with db.tenant_session(tenant_id) as session:
        for table in (
            "job_queue",
            "webhook_deliveries",
            "webhook_endpoints",
            "synced_entities",
            "sync_checkpoints",
            "tenant_stores",
            "tenants",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
            )


async def held(db: Database, tenant_id: str) -> int:
    entities = DatabaseEntityStore(db, tenant_id)
    return sum([await entities.count(tenant_id, "generic", t) for t in SYNCED_TYPES])


async def wait_for(db: Database, tenant_id: str, job_id: str) -> tuple[JobStatus, str, float]:
    """Poll until the worker finishes the job, or the ceiling is reached."""
    started = datetime.now(UTC)
    while (elapsed := (datetime.now(UTC) - started).total_seconds()) < TIMEOUT_S:
        async with db.tenant_session(tenant_id) as session:
            job = await JobQueue(session).get(job_id)
        if job is not None and job.status in (JobStatus.DONE, JobStatus.DEAD):
            return job.status, job.last_error, elapsed
        await asyncio.sleep(0.5)
    return JobStatus.PENDING, "timed out waiting for a worker", TIMEOUT_S


async def demo(url: str, token: str, *, keep: bool) -> int:
    db = Database.from_settings()

    # A database connected as a role RLS does not apply to is a refusal, not a
    # warning — see ADR-0008. `ping` is what enforces it.
    if not await db.ping():
        print("\n  \033[31mNo database at DATABASE_URL — run `make up && make migrate`.\033[0m\n")
        return 1

    tenant_id = new_id(TENANT)
    ok = True

    print("\n  A TENANT NOBODY HAS HEARD OF")
    print(f"    {dim('id')}        {tenant_id}")
    print(f"    {dim('shop')}      {url}")

    # ── The worker, started before the tenant exists ─────────────────────────
    print("\n  WORKER — a separate process, given a database and nothing else")
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        __file__,
        "--worker",
        "--poll-interval",
        str(DEMO_POLL_S),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert worker.stdout is not None
    try:
        first_line = await asyncio.wait_for(worker.stdout.readline(), timeout=30)
    except TimeoutError:
        print("    \033[31m✘\033[0m the worker did not start")
        worker.terminate()
        return 1
    print(f"    {tick(True)} pid {worker.pid} · {first_line.decode().strip()}")

    tail: list[str] = []
    draining = asyncio.create_task(_drain(worker.stdout, tail))

    try:
        # ── The check that makes the rest mean anything ──────────────────────
        #
        # If this list is not empty of our tenant, a later success proves
        # nothing: it would be equally consistent with a worker that had been
        # handed the tenant from the start.
        print("\n  BEFORE — does anything know this tenant has work?")
        named = await due_tenants(db)
        unknown = tenant_id not in named
        others = "nobody" if not named else f"{len(named)} other tenant(s)"
        print(
            f"    {tick(unknown)} neura_due_tenants() names {others}, "
            f"and {'not this one' if unknown else '\033[31mTHIS ONE\033[0m'}"
        )
        ok = ok and unknown

        # ── Create the tenant and schedule the work, from outside ────────────
        print("\n  SCHEDULE — in this process, which the worker cannot see")
        store_id = await provision(db, tenant_id, url, token)
        print(f"    {tick(True)} tenant created · store {store_id} registered")

        async with db.tenant_session(tenant_id) as session:
            job = await enqueue_sync(session, tenant_id, store_id=store_id, incremental=False)
        print(f"    {tick(True)} enqueued {job.kind} · {job.id}")

        # ── The dispatch function now names it, and nothing was told ─────────
        named = await due_tenants(db)
        found = tenant_id in named
        print(
            f"    {tick(found)} neura_due_tenants() now names it — "
            "one column, one function, no BYPASSRLS"
        )
        ok = ok and found

        # ── The worker finds it, opens a session, and syncs the real shop ────
        print("\n  THE WORKER, UNPROMPTED")
        status, error, elapsed = await wait_for(db, tenant_id, job.id)
        done = status is JobStatus.DONE
        print(
            f"    {tick(done)} job {status.value} after {elapsed:.1f}s"
            + (f" — {error}" if error else "")
        )
        ok = ok and done

        entities = await held(db, tenant_id)
        synced = entities > 0
        print(
            f"    {tick(synced)} {entities} entities synced from the real shop "
            "into a tenant the worker was never told about"
        )
        ok = ok and synced

        # ── One live sync per store, not one per request ─────────────────────
        print("\n  ASKED AGAIN, AFTER THE FIRST FINISHED — must be a NEW sync")
        async with db.tenant_session(tenant_id) as session:
            again = await enqueue_sync(session, tenant_id, store_id=store_id)
            rows = await JobQueue(session).list_for(tenant_id)
        # The first job has finished by now, so this must be a *new* one — the
        # dedupe key covers live rows only. A permanent constraint here would
        # mean this store could never be synced again, which is exactly the
        # defect this check missed on the day the queue shipped.
        one = len(rows) == 2 and again.id != job.id
        print(f"    {tick(one)} the finished job freed its key, so a second sync could be queued")
        ok = ok and one

        # ── The outbox, on the same queue ────────────────────────────────────
        print("\n  THE OUTBOX — the Redis index, replaced")
        ok = await drain_act(db, tenant_id) and ok

    finally:
        draining.cancel()
        worker.terminate()
        await worker.wait()
        if keep:
            print(f"\n  --keep: tenant {tenant_id} left in place.")
            print(f"          remove it with: make job-drop TENANT={tenant_id}")
        else:
            await forget(db, tenant_id)
        await db.dispose()

    print()
    if ok:
        print("  \033[32mA sync ran for a tenant the worker did not know existed,\033[0m")
        print("  \033[32mand a signed webhook reached a merchant off the same queue.\033[0m")
        print(dim("  That is P7. The schedule is a row in the same database as the work,"))
        print(dim("  and the only thing that crossed a tenant boundary was a list of ids."))
    else:
        print("  \033[31mThe scheduler did not do what ADR-0022 says it does.\033[0m")
    print()
    return 0 if ok else 1


async def drain_act(db: Database, tenant_id: str) -> bool:
    """Queue a real webhook and watch the worker sign and deliver it."""
    merchant = Merchant()
    await merchant.start()
    ok = True
    try:
        async with db.tenant_session(tenant_id) as session:
            repository = WebhookRepository(session)
            endpoint, secret = await repository.register(
                tenant_id,
                url=merchant.url,
                events=[WebhookEvent.CONVERSATION_RESOLVED],
            )
            event = PendingEvent(event=WebhookEvent.CONVERSATION_RESOLVED)
            deliveries = await repository.enqueue(tenant_id, event)
            # In the same transaction as the deliveries. The old Redis `sadd`
            # could only happen *after* the commit, so a process that died in
            # between stranded them permanently.
            drain = await enqueue_drain(session, tenant_id)
        print(f"    {tick(bool(deliveries))} endpoint {endpoint.id} registered · event queued")
        print(f"    {tick(True)} drain job {drain.id} written in the same transaction")

        status, error, elapsed = await wait_for(db, tenant_id, drain.id)
        done = status is JobStatus.DONE
        print(
            f"    {tick(done)} drain {status.value} after {elapsed:.1f}s"
            + (f" — {error}" if error else "")
        )
        ok = ok and done

        arrived = bool(merchant.received)
        print(f"    {tick(arrived)} the merchant's endpoint received {len(merchant.received)} POST")
        ok = ok and arrived

        if arrived:
            headers, body = merchant.received[0]
            signed = matches(
                body,
                headers.get(SIGNATURE_HEADER.lower(), ""),
                secret,
                timestamp=int(headers.get(TIMESTAMP_HEADER.lower(), "0")),
            )
            print(
                f"    {tick(signed)} the signature verifies against the merchant's own secret "
                f"· {headers.get(EVENT_TYPE_HEADER.lower(), '?')}"
            )
            ok = ok and signed
    finally:
        await merchant.stop()
    return ok


async def drop(tenant_id: str) -> int:
    db = Database.from_settings()
    if not await db.ping():
        return 1
    await forget(db, tenant_id)
    await db.dispose()
    print(f"  removed {tenant_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="the shop's Neura endpoint")
    parser.add_argument("--token", help="the shop's API token")
    parser.add_argument("--worker", action="store_true", help="run only the worker loop")
    parser.add_argument("--poll-interval", type=float, default=DEMO_POLL_S)
    parser.add_argument("--keep", action="store_true", help="leave the tenant in place")
    parser.add_argument("--drop", metavar="TENANT", help="remove a tenant left by --keep")
    return parser


async def main() -> int:
    args = build_parser().parse_args()
    configure_logging(level="WARNING" if not args.worker else "INFO")

    if args.worker:
        return await run_worker(args.poll_interval)
    if args.drop:
        return await drop(args.drop)
    if not args.url or not args.token:
        print("usage: make job-check URL=http://your-shop/neura/v1 TOKEN=xxx", file=sys.stderr)
        return 2
    return await demo(args.url, args.token, keep=args.keep)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
