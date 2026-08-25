"""The worker: the loop, and the handlers it dispatches to.

``neura_core.jobs`` owns the queue and the one narrow function that finds work
across tenants. This package owns the process that calls them, and knows what a
job actually *does*.
"""

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

__all__ = [
    "CLAIM_LIMIT",
    "POLL_INTERVAL_S",
    "SYNC_STORE",
    "Handler",
    "JobContext",
    "JobRunner",
    "SyncJobFailedError",
    "SyncStoreHandler",
    "UnknownJobKindError",
    "enqueue_sync",
]
