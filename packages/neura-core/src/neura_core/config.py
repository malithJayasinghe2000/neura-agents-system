"""Configuration — environment-driven, validated, fail-fast.

A misconfigured deployment must not start. Every setting is validated at import
of :func:`get_settings`, so a missing secret is a boot failure rather than a
500 discovered by a customer.

Mirrors ``.env.example``; keep the two in step.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
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
    #
    # The user is `neura_app`, NOT the owner `neura`. PostgreSQL exempts
    # superusers and BYPASSRLS roles from Row-Level Security, so connecting as
    # the owner would switch tenant isolation off with no error anywhere —
    # every query would simply start working across tenants. `Database.ping`
    # checks the connected role for exactly this (ADR-0008).
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://neura_app:neura_app@localhost:5433/neura"),
        alias="DATABASE_URL",
    )
    #: Migrations need to CREATE TABLE and ALTER POLICY, which the application
    #: role deliberately cannot do. A separate URL keeps that privilege out of
    #: the process that serves requests.
    database_migration_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://neura:neura@localhost:5433/neura"),
        alias="DATABASE_MIGRATION_URL",
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

    # ── Rate limits (ADR-0017) ───────────────────────────────────────────────
    #
    # Every one of these is a guess. They are informed starting points and must
    # not be quoted as measurements (CLAUDE.md §4) — nothing here has seen a
    # real shopper. They are configuration for exactly that reason, and the
    # trigger to recalibrate is E3's: roughly a hundred real conversations.
    #
    # A request is checked against several subjects at once and all must pass;
    # the response headers report the tightest. `tenant` is the merchant-wide
    # backstop, `key` bounds one credential, and `client` and `conversation`
    # are the two narrower subjects a shared `fn_pk_` key needs.
    rate_limit_window_s: int = Field(default=60, alias="RATE_LIMIT_WINDOW_S")
    rate_limit_per_tenant: int = Field(default=600, alias="RATE_LIMIT_PER_TENANT")
    rate_limit_per_key: int = Field(default=600, alias="RATE_LIMIT_PER_KEY")
    #: Sized for a shared address — an office or a household behind one NAT —
    #: not for one person, because that is what an IP identifies.
    rate_limit_per_client: int = Field(default=40, alias="RATE_LIMIT_PER_CLIENT")
    rate_limit_per_conversation: int = Field(default=20, alias="RATE_LIMIT_PER_CONVERSATION")
    #: The developer MCP server answers anyone, with no key (ADR-0053 §3), so a
    #: client address is the only subject it has. **A guess**, to be set from
    #: real use (CLAUDE.md §4): an AI tool building a bridge asks a few dozen
    #: questions, not hundreds a minute.
    rate_limit_developer_mcp: int = Field(default=60, alias="RATE_LIMIT_DEVELOPER_MCP")
    #: Asking for a sign-in link (G97), counted over an hour per network address
    #: and per email. **Guesses**, to be set from real use (CLAUDE.md §4): a person
    #: asks for a link or two; an office shares one address. Without them anyone
    #: could make NEURA send any number of emails to one inbox.
    rate_limit_sign_in_window_s: int = Field(default=3600, alias="RATE_LIMIT_SIGN_IN_WINDOW_S")
    rate_limit_sign_in_per_client: int = Field(default=20, alias="RATE_LIMIT_SIGN_IN_PER_CLIENT")
    rate_limit_sign_in_per_email: int = Field(default=5, alias="RATE_LIMIT_SIGN_IN_PER_EMAIL")

    #: How many proxies sit in front of this deployment. **Zero means
    #: ``X-Forwarded-For`` is ignored entirely**, which is the only safe default:
    #: the header is attacker-controlled, and trusting it makes the narrowest
    #: rate-limit subject free to rotate while the limiter carries on reporting
    #: plausible numbers. A hop count rather than an allowlist, because it is a
    #: fact about this deployment's own topology (ADR-0017 §2).
    trusted_proxy_hops: int = Field(default=0, ge=0, alias="NEURA_TRUSTED_PROXY_HOPS")

    # ── Conversations ────────────────────────────────────────────────────────
    #: How many previous turns are replayed into a prompt. Bounded because the
    #: history is tokens: an unbounded transcript is an unbounded bill and,
    #: eventually, a context window that truncates the part that mattered.
    conversation_history_turns: int = Field(default=6, ge=0, alias="CONVERSATION_HISTORY_TURNS")

    # ── Retention (days) — enforced by `neura_api.jobs.retention` ────────────
    #: A conversation untouched for this long is deleted — transcript, messages
    #: and the agent's saved working state together (security-model.md §6.2).
    #: Read by code since 2026-09-26; it sat in `.env` unread for weeks before
    #: that (ADR-0042 §3).
    retention_conversations_days: int = Field(
        default=90, ge=1, alias="RETENTION_CONVERSATIONS_DAYS"
    )
    #: How long an observed event is held (ADR-0044 §7). **Seven**, because the
    #: longest window anything designed reads is a week — ADR-0046's sold-out
    #: count and ADR-0044 §6's "third visit in a week" — and a page view older
    #: than every use for it is, in §7's words, pure liability.
    retention_observed_events_days: int = Field(
        default=7, ge=1, alias="RETENTION_OBSERVED_EVENTS_DAYS"
    )
    #: How long a handed-over shopper's typed email waits for the shop's answer
    #: (ADR-0062 §4, the owner's R30). *Mark as answered* deletes it at once;
    #: unanswered, it goes after this many days and the chat leaves the waiting
    #: list. Thirty is a guess (CLAUDE.md §4).
    retention_handover_emails_days: int = Field(
        default=30, ge=1, alias="RETENTION_HANDOVER_EMAILS_DAYS"
    )
    # RETENTION_AUDIT_LOG_DAYS and RETENTION_TRACES_DAYS are deliberately NOT
    # fields. Neither is enforced (ADR-0048 §5), and a field nothing acts on is
    # the failure ADR-0042 §3 warned about — a setting that appears to work.

    # ── Observability ────────────────────────────────────────────────────────
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field(default="neura-api", alias="OTEL_SERVICE_NAME")

    # ── Widget ───────────────────────────────────────────────────────────────
    #: Origins permitted on endpoints that have **no key to consult** — the
    #: widget asset and health. Every keyed request is decided by the presented
    #: key's own allowlist instead (ADR-0014 §3, ADR-0019 §3), which is what
    #: makes onboarding a merchant a key issue rather than a redeploy.
    widget_allowed_origins: str = Field(
        default="http://localhost:3000", alias="WIDGET_ALLOWED_ORIGINS"
    )
    #: How this API is reachable from a merchant's page. It builds the chat box
    #: line and the developer AI tool address (ADR-0053), and that tool accepts
    #: requests for this host only. It cannot be derived from an incoming
    #: request, because the request that asks for the snippet is usually not the
    #: one a shopper's browser will make. **Empty in development means this
    #: machine at `NEURA_API_PORT`; outside development it must be set** (G24):
    #: a default there is never right, and nothing would say so.
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")

    # ── Email (ADR-0026, open question K1) ────────────────────────────────────
    #
    # Plain SMTP rather than a hosted provider's SDK, and that is the sovereign
    # tier's requirement rather than a preference: a customer running everything
    # inside their own perimeter can point this at their own mail server, and
    # cannot point it at an API key for a service in another country. A hosted
    # provider may be added ALONGSIDE this; it must never replace it.
    #
    # Empty `smtp_host` is not a misconfiguration — it is the ordinary state of
    # every developer machine and every test run. Sending is skipped and said so
    # out loud; see `neura_core.email`.
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASS")
    smtp_from: str = Field(default="FiveNeurals <no-reply@example.com>", alias="SMTP_FROM")

    #: Where sign-in links point. **Must** match where the console is actually
    #: served or every link 404s — and a login link that 404s is indistinguishable
    #: from a broken product to the person holding it. The default is for
    #: development only; outside it, it must be set (G77).
    console_base_url: str = Field(default="http://localhost:3000", alias="CONSOLE_BASE_URL")
    #: What a shopper is shown when the reply is withheld and the tenant has
    #: configured no wording of its own (ADR-0020). **It promises nothing**: a
    #: shadowed turn tells no person, so a default about somebody getting back
    #: to them would be an offer nothing can honour — the A9(3) failure, shipped
    #: as a platform string on the one path where no verifier runs.
    widget_withheld_message: str = Field(
        default=(
            "Thanks — your message has been received. There is no automated "
            "answer available for it right now."
        ),
        alias="WIDGET_WITHHELD_MESSAGE",
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

    @model_validator(mode="after")
    def _public_address(self) -> Settings:
        # Every use appends a path, so a trailing slash would double it.
        self.public_base_url = self.public_base_url.strip().rstrip("/")
        if not self.public_base_url and self.env is Environment.DEVELOPMENT:
            self.public_base_url = f"http://localhost:{self.api_port}"
        return self

    def validate_for_runtime(self) -> None:
        """Reject configurations that are unsafe to serve real traffic with.

        Placeholder secrets and this machine's addresses are tolerated in
        development so the stack boots from a fresh clone, and rejected
        everywhere else. Every problem is named at once, not one per restart.
        """
        if self.env is Environment.DEVELOPMENT:
            return

        placeholders = [
            name
            for name, value in (("NEURA_SECRET_KEY", self.secret_key), ("NEURA_KEK", self.kek))
            if value == _PLACEHOLDER
        ]
        problems = [f"{name} is still set to the placeholder value" for name in placeholders]
        fields = list(placeholders)

        # The two addresses NEURA hands to other people (G24, G77). A wrong one
        # fails for them, silently: a chat box line, a developer AI tool address
        # or a sign-in link that leads to the machine NEURA runs on.
        for name, field, value in (
            ("PUBLIC_BASE_URL", "public_base_url", self.public_base_url),
            ("CONSOLE_BASE_URL", "console_base_url", self.console_base_url),
        ):
            if field not in self.model_fields_set or not value.strip():
                problems.append(f"{name} is not set")
            elif self.is_production and (reason := _not_public_https(value)):
                problems.append(f"{name} {reason}")
            else:
                continue
            fields.append(name)

        if problems:
            raise ConfigurationError(
                f"Refusing to start in {self.env}: {'; '.join(problems)}.",
                details={"fields": fields},
            )


def _not_public_https(address: str) -> str | None:
    """Why an address may not be given to shops and owners in production, or ``None``."""
    parts = urlsplit(address.strip())
    if parts.scheme != "https":
        return "must start with https://"
    host = parts.hostname
    if not host:
        return "has no host"
    if host == "localhost" or host.endswith(".localhost"):
        return "points at this machine"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None  # a name: whether it is public is the DNS's to say
    return None if ip.is_global else "is not a public internet address"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Cached — configuration does not change at runtime."""
    return Settings()
