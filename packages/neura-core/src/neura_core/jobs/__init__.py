"""Durable background work, and the one narrow way a worker finds it.

``job_queue`` is an ordinary tenant table under forced Row-Level Security;
:class:`JobQueue` reads and writes it inside a scoped session like everything
else. :func:`due_tenants` is the exception the whole package exists to bound —
one function, one column, one list of tenant ids
([ADR-0022](../../../../docs/architecture/adr/0022-scheduling-under-rls.md)).

Nothing here knows what a job *does*. Handlers are registered by the deployable,
because a queue that knew about syncing would be a queue that has to change
every time a new kind of work appears.
"""

from neura_core.jobs.dispatch import due_tenants
from neura_core.jobs.models import (
    BACKOFF_BASE_S,
    BACKOFF_MAX_S,
    DEFAULT_LEASE,
    Job,
    JobStatus,
    backoff_for,
)
from neura_core.jobs.queue import CrossTenantJobWriteError, JobQueue
from neura_core.jobs.schema import (
    DUE_TENANTS_FUNCTION,
    JOB_QUEUE_TABLE,
    SCHEDULER_ROLE,
    job_queue,
)

__all__ = [
    "BACKOFF_BASE_S",
    "BACKOFF_MAX_S",
    "DEFAULT_LEASE",
    "DUE_TENANTS_FUNCTION",
    "JOB_QUEUE_TABLE",
    "SCHEDULER_ROLE",
    "CrossTenantJobWriteError",
    "Job",
    "JobQueue",
    "JobStatus",
    "backoff_for",
    "due_tenants",
    "job_queue",
]
