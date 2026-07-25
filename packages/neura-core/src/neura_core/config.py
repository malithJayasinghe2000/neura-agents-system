"""Configuration — environment-driven, validated, fail-fast.

A misconfigured deployment must not start. Every setting is validated at import
of :func:`get_settings`, so a missing secret is a boot failure rather than a
500 discovered by a customer.

Mirrors ``.env.example``; keep the two in step.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neura_core.errors import ConfigurationError

_PLACEHOLDER = "change-me"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────────────────
    env: Environment = Field(default=Environment.DEVELOPMENT, alias="NEURA_ENV")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="NEURA_LOG_LEVEL"
    )
    api_host: str = Field(default="0.0.0.0", alias="NEURA_API_HOST")  # noqa: S104
    api_port: int = Field(default=8000, alias="NEURA_API_PORT")
    secret_key: str = Field(default=_PLACEHOLDER, alias="NEURA_SECRET_KEY")

    # ── Datastores ───────────────────────────────────────────────────────────
    # Port 5433, not 5432: the dev stack deliberately avoids colliding with a
    # Postgres the developer may already run. See docker-compose.yml.
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://neura:neura@localhost:5433/neura"),
        alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=5, alias="DATABASE_MAX_OVERFLOW")
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"), alias="REDIS_URL")

    # ── Encryption ───────────────────────────────────────────────────────────
    kek: str = Field(default=_PLACEHOLDER, alias="NEURA_KEK")

    # ── LLM ──────────────────────────────────────────────────────────────────
    role_map: str = Field(default="ollama-dev", alias="NEURA_ROLE_MAP")
    ollama_base_url: str = Field(default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL")
    ollama_api_key: str = Field(default="ollama", alias="OLLAMA_API_KEY")
    cloud_llm_base_url: str | None = Field(default=None, alias="CLOUD_LLM_BASE_URL")
    cloud_llm_api_key: str | None = Field(default=None, alias="CLOUD_LLM_API_KEY")

    # ── Budgets (defaults; overridable per tenant) ───────────────────────────
    budget_daily_cost_usd_soft: float = Field(default=8.0, alias="BUDGET_DAILY_COST_USD_SOFT")
    budget_daily_cost_usd_hard: float = Field(default=12.0, alias="BUDGET_DAILY_COST_USD_HARD")
    budget_conversation_max_tokens: int = Field(
        default=40_000, alias="BUDGET_CONVERSATION_MAX_TOKENS"
    )
    budget_conversation_max_llm_calls: int = Field(
        default=25, alias="BUDGET_CONVERSATION_MAX_LLM_CALLS"
    )
    budget_turn_max_tool_calls: int = Field(default=4, alias="BUDGET_TURN_MAX_TOOL_CALLS")

    # ── Observability ────────────────────────────────────────────────────────
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field(default="neura-api", alias="OTEL_SERVICE_NAME")

    # ── Widget ───────────────────────────────────────────────────────────────
    widget_allowed_origins: str = Field(
        default="http://localhost:3000", alias="WIDGET_ALLOWED_ORIGINS"
    )

    # ── Derived ──────────────────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.env is Environment.PRODUCTION

    @property
    def widget_origins(self) -> list[str]:
        return [o.strip() for o in self.widget_allowed_origins.split(",") if o.strip()]

    @field_validator("budget_daily_cost_usd_hard")
    @classmethod
    def _hard_above_soft(cls, v: float, info: object) -> float:
        # Pydantic passes previously-validated fields in info.data; a hard ceiling
        # below the soft one would make the degradation ladder nonsensical.
        data = getattr(info, "data", {})
        soft = data.get("budget_daily_cost_usd_soft")
        if soft is not None and v < soft:
            raise ValueError("BUDGET_DAILY_COST_USD_HARD must be >= ..._SOFT")
        return v

    def validate_for_runtime(self) -> None:
        """Reject configurations that are unsafe to serve real traffic with.

        Placeholder secrets are tolerated in development so the stack boots from a
        fresh clone, and rejected everywhere else.
        """
        if self.env is Environment.DEVELOPMENT:
            return

        placeholders = [
            name
            for name, value in (("NEURA_SECRET_KEY", self.secret_key), ("NEURA_KEK", self.kek))
            if value == _PLACEHOLDER
        ]
        if placeholders:
            raise ConfigurationError(
                f"Refusing to start in {self.env}: {', '.join(placeholders)} "
                "still set to the placeholder value.",
                details={"fields": placeholders},
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Cached — configuration does not change at runtime."""
    return Settings()
