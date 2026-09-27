"""The worker: the loop, and the handlers it dispatches to.

``neura_core.jobs`` owns the queue and the one narrow function that finds work
across tenants. This package owns the process that calls them, and knows what a
job actually *does*.
"""

from neura_api.jobs.retention import (
    RETENTION_SWEEP,
    RetentionSweepHandler,
    SweepResult,
    enqueue_sweep,
    sweep,
)
from neura_api.jobs.runner import (
    CLAIM_LIMIT,
    POLL_INTERVAL_S,
    Handler,
    JobContext,
    JobRunner,
    UnknownJobKindError,
)
from neura_api.jobs.sync import (
    SYNC_STORE,
    SyncJobFailedError,
    SyncStoreHandler,
    enqueue_sync,
)
from neura_api.jobs.webhooks import (
    WEBHOOK_DRAIN,
    WebhookDrainHandler,
    enqueue_drain,
)

__all__ = [
    "CLAIM_LIMIT",
    "POLL_INTERVAL_S",
    "RETENTION_SWEEP",
    "SYNC_STORE",
    "WEBHOOK_DRAIN",
    "Handler",
    "JobContext",
    "JobRunner",
    "RetentionSweepHandler",
    "SweepResult",
    "SyncJobFailedError",
    "SyncStoreHandler",
    "UnknownJobKindError",
    "WebhookDrainHandler",
    "enqueue_drain",
    "enqueue_sweep",
    "enqueue_sync",
    "sweep",
]
