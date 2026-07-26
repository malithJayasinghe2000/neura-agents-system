"""Rate limiting, per tenant.

**We must never be the reason a merchant's shop falls over.** A backfill is the
most aggressive thing this system ever does to a customer's production server —
hundreds of sequential requests, often against a small VPS shared with the
storefront real shoppers are using.

A token bucket rather than a fixed delay, because the traffic we want is bursty:
a handful of quick calls when a webhook arrives, then nothing for an hour. A
fixed sleep would make the urgent case slow in order to make the bulk case
polite.

Per tenant, because one merchant's backfill must not slow every other tenant's
agent to a crawl.
"""

from __future__ import annotations

import asyncio
import time

#: Deliberately conservative. A shop we do not know is a shop we assume is
#: small; the merchant can be given more once their infrastructure is known.
DEFAULT_RATE_PER_SECOND = 5.0
DEFAULT_BURST = 10


class RateLimiter:
    """Token bucket with an explicit pause for ``Retry-After``."""

    def __init__(
        self,
        rate_per_second: float = DEFAULT_RATE_PER_SECOND,
        burst: int = DEFAULT_BURST,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")

        self._rate = rate_per_second
        self._capacity = float(max(burst, 1))
        self._tokens = self._capacity
        self._updated_at = time.monotonic()
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until one request may be made."""
        while True:
            async with self._lock:
                now = time.monotonic()

                if now >= self._paused_until:
                    self._refill(now)

                    if self._tokens >= 1:
                        self._tokens -= 1
                        return

                    wait = max((1 - self._tokens) / self._rate, 0.0)
                else:
                    wait = self._paused_until - now

            # Slept outside the lock: holding it while waiting would serialise
            # every caller behind the unluckiest one.
            await asyncio.sleep(wait)

    def pause(self, seconds: float) -> None:
        """Honour a store's ``Retry-After``.

        The shop has said, explicitly, that it wants less traffic. Ignoring that
        is how an integration gets a merchant's host to block us — and being
        blocked takes the agent down for that shop entirely.
        """
        if seconds <= 0:
            return

        self._paused_until = max(self._paused_until, time.monotonic() + seconds)
        # Drain the bucket too, so the moment the pause lifts we do not
        # immediately spend a full burst on a shop that just asked us to stop.
        self._tokens = 0.0

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated_at
        self._updated_at = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)


class NoLimit:
    """No throttling. For tests, and for a shop we host ourselves."""

    async def acquire(self) -> None:
        return

    def pause(self, seconds: float) -> None:
        return
