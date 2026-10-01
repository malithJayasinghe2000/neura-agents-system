"""Rate limiting — several subjects at once, and the narrowest one wins.

The decision and its reasoning are ADR-0017. In short: per-key is the wrong unit
for a widget where every shopper shares one `fn_pk_` key, so a request is checked
against a *set* of subjects and all of them must pass. The headers report the
tightest.

Two properties this module is arranged around, both of which are easy to get
wrong in a way that produces no error:

* **The counters live in Redis, not in this process.** One deployable is not one
  process; an in-process counter multiplies every configured limit by the worker
  count while continuing to report the configured number, and nobody
  investigates a control that looks right.
* **It fails open, loudly.** A rate limiter is not an access control —
  authentication, entitlements, the policy engine and the ownership gate are all
  still in the path — and the *cost* ceiling is a Postgres rollup that survives
  Redis being gone. Failing closed would turn a cache outage into a total outage
  for every merchant at once.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass

from neura_core import RateLimitError, get_logger, get_settings
from neura_core.tenancy import ApiKeyKind, AuthenticatedCaller

log = get_logger(__name__)

KEY_PREFIX = "neura:rl"


@dataclass(frozen=True, slots=True)
class Subject:
    """One thing being limited, and how much of it is allowed."""

    kind: str
    identity: str
    limit: int

    def bucket(self, *, window_s: int, now: float) -> str:
        """The Redis key for the current fixed window.

        The window number is in the key, so expiry is the only cleanup needed
        and a window rolls over without anything having to reset a counter.
        """
        window = int(now // window_s)
        return f"{KEY_PREFIX}:{self.kind}:{self.identity}:{window}"


@dataclass(frozen=True, slots=True)
class Verdict:
    """The outcome, and the numbers that go in the headers.

    ``limit``, ``remaining`` and ``reset`` describe the **binding** subject — the
    one with least room left. A client backing off on these backs off on the
    constraint that will actually stop it, which is the whole point of returning
    them (api-design.md §6).
    """

    allowed: bool
    limit: int
    remaining: int
    reset: int
    subject: str = ""

    @property
    def retry_after(self) -> int:
        return max(self.reset - int(time.time()), 1)

    def headers(self) -> dict[str, str]:
        values = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(self.remaining, 0)),
            "X-RateLimit-Reset": str(self.reset),
        }
        if not self.allowed:
            values["Retry-After"] = str(self.retry_after)
        return values


def subjects_for(
    caller: AuthenticatedCaller,
    *,
    client: str,
    conversation_id: str | None,
) -> list[Subject]:
    """Which subjects apply to this caller (ADR-0017 §1).

    A **secret** key is the merchant's own server: the key and the tenant are
    the only meaningful units, and narrowing further would throttle a legitimate
    batch integration for no security gain.

    A **public** key is served to every browser that loads the storefront, so it
    identifies the shop and not the shopper. Two narrower subjects do that job,
    and neither is sufficient alone — the conversation constrains an honest
    client, the client address constrains a dishonest one.
    """
    settings = get_settings()
    applicable = [
        Subject("tenant", caller.tenant_id, settings.rate_limit_per_tenant),
        Subject("key", caller.api_key.id, settings.rate_limit_per_key),
    ]

    if caller.api_key.kind is ApiKeyKind.PUBLIC:
        applicable.append(
            Subject(
                "client", _fingerprint(caller.api_key.id, client), settings.rate_limit_per_client
            )
        )
        if conversation_id:
            applicable.append(
                Subject("conversation", conversation_id, settings.rate_limit_per_conversation)
            )

    return applicable


def anonymous_client(kind: str, client: str, limit: int) -> Subject:
    """The one subject a caller with **no key at all** has: its address.

    For a public surface that holds nothing worth protecting, the developer MCP
    server (ADR-0053 §3). The address is fingerprinted exactly as a widget
    client's is, scoped by ``kind`` instead of a key id, so it is never stored.
    """
    return Subject(kind, _fingerprint(kind, client), limit)


def _fingerprint(key_id: str, client: str) -> str:
    """Hash the client address, keyed with the deployment secret.

    **The address is never stored.** An IP is personal data; what goes into
    Redis is a truncated keyed hash inside a counter key that expires with its
    window. Keyed rather than plain so the values cannot be reversed by
    enumerating the address space, and scoped by key id so one merchant's
    counters cannot be probed from another's.
    """
    secret = get_settings().secret_key.encode()
    digest = hashlib.sha256(secret + key_id.encode() + b"|" + client.encode()).hexdigest()
    return digest[:32]


class RateLimiter:
    """Fixed-window counters in Redis.

    Fixed window rather than sliding: a sliding window costs a sorted set per
    subject per window, and its advantage is bounded — two full allowances can
    be spent across a boundary, which ``X-RateLimit-Reset`` at least makes
    predictable rather than mysterious. Recorded as an accepted limitation in
    ADR-0017 rather than left for someone to discover.
    """

    def __init__(self, redis: object | None, *, window_s: int | None = None) -> None:
        self._redis = redis
        self._window_s = window_s or get_settings().rate_limit_window_s

    @property
    def available(self) -> bool:
        return self._redis is not None

    async def check(self, subjects: Sequence[Subject], *, now: float | None = None) -> Verdict:
        """Consume one request against every subject and return the tightest.

        **Every subject is incremented, including after one has already
        refused.** The alternative — stopping at the first failure — leaves the
        remaining counters under-counting exactly when a caller is at their
        limit, so a client that ignores 429s would slowly drift below its real
        usage on every other subject.
        """
        moment = now if now is not None else time.time()
        window_end = (int(moment // self._window_s) + 1) * self._window_s

        if self._redis is None:
            # Fail open, and say so every time. A silent failure here is a
            # control that has stopped working and still looks enabled.
            log.error("rate_limit_unavailable", detail="no Redis; request allowed unmetered")
            widest = max((s.limit for s in subjects), default=0)
            return Verdict(allowed=True, limit=widest, remaining=widest, reset=window_end)

        tightest: Verdict | None = None
        for subject in subjects:
            used = await self._increment(subject.bucket(window_s=self._window_s, now=moment))
            if used is None:
                continue
            verdict = Verdict(
                allowed=used <= subject.limit,
                limit=subject.limit,
                remaining=subject.limit - used,
                reset=window_end,
                subject=subject.kind,
            )
            if tightest is None or _tighter(verdict, tightest):
                tightest = verdict

        if tightest is None:
            log.error("rate_limit_unavailable", detail="Redis unreachable; request allowed")
            widest = max((s.limit for s in subjects), default=0)
            return Verdict(allowed=True, limit=widest, remaining=widest, reset=window_end)
        return tightest

    async def _increment(self, key: str) -> int | None:
        """``INCR`` then ``EXPIRE``. ``None`` means Redis could not be reached."""
        try:
            pipeline = self._redis.pipeline()  # type: ignore[union-attr]
            pipeline.incr(key)
            # Set on every request rather than only on creation: an EXPIRE that
            # is skipped because the key "already existed" is how a counter
            # becomes immortal after a race, and an immortal counter locks a
            # subject out permanently.
            pipeline.expire(key, self._window_s + 1)
            used, _ = await pipeline.execute()
            return int(used)
        except Exception as exc:
            log.error("rate_limit_backend_error", error=str(exc), key_kind=key.split(":")[2])
            return None


def _tighter(candidate: Verdict, current: Verdict) -> bool:
    """A refusal always wins; otherwise the one with least room left."""
    if candidate.allowed != current.allowed:
        return not candidate.allowed
    return candidate.remaining < current.remaining


def enforce(verdict: Verdict) -> None:
    """Raise the 429 api-design.md §6 specifies, with its ``Retry-After``.

    A rate limit is the one cost control in this system that *errors*. A
    **budget** still degrades to escalate-only and never errors (ADR-0015),
    because the two reach different people: a 429 reaches a client, which can
    wait; a budget reaches a shopper, who cannot and did not set the ceiling.
    """
    if verdict.allowed:
        return
    raise RateLimitError(
        "Too many requests. Retry after the window resets.",
        details={
            "subject": verdict.subject,
            "limit": verdict.limit,
            "reset": verdict.reset,
            "retry_after": verdict.retry_after,
        },
    )


__all__ = [
    "KEY_PREFIX",
    "RateLimiter",
    "Subject",
    "Verdict",
    "anonymous_client",
    "enforce",
    "subjects_for",
]
