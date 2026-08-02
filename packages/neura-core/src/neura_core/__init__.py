"""neura-core — shared infrastructure.

Config, structured logging, the error hierarchy, request context, telemetry,
identifiers, envelope encryption, and the database seam. The bottom of the
dependency graph: this package imports nothing else from the workspace.
"""

from neura_core.config import Environment, Settings, get_settings
from neura_core.context import (
    bind_context,
    current_context,
    get_conversation_id,
    get_tenant_id,
    get_trace_id,
)
from neura_core.db import (
    CREDENTIAL_SETTING,
    TENANT_SETTING,
    Database,
    get_database,
    metadata,
)
from neura_core.env import find_env_file, load_env
from neura_core.errors import (
    AgentNotEnabledError,
    AuthenticationError,
    BudgetExceededError,
    ConfigurationError,
    ConflictError,
    ForbiddenError,
    IdempotencyConflictError,
    NeuraError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from neura_core.ids import new_id
from neura_core.logging import configure_logging, get_logger
from neura_core.telemetry import configure_telemetry, current_trace_id, get_tracer

__all__ = [
    "CREDENTIAL_SETTING",
    "TENANT_SETTING",
    "AgentNotEnabledError",
    "AuthenticationError",
    "BudgetExceededError",
    "ConfigurationError",
    "ConflictError",
    "Database",
    "Environment",
    "ForbiddenError",
    "IdempotencyConflictError",
    "NeuraError",
    "NotFoundError",
    "RateLimitError",
    "ServiceUnavailableError",
    "Settings",
    "ValidationError",
    "bind_context",
    "configure_logging",
    "configure_telemetry",
    "current_context",
    "current_trace_id",
    "find_env_file",
    "get_conversation_id",
    "get_database",
    "get_logger",
    "get_settings",
    "get_tenant_id",
    "get_trace_id",
    "get_tracer",
    "load_env",
    "metadata",
    "new_id",
]
