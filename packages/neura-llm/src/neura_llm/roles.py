"""Model roles — the mechanism that makes dev→production a config change.

Application code asks for a **role**, never a model:

    client.chat(ModelRole.ROUTER, request)     # yes
    client.chat("llama3.2:3b", request)         # never

A role map binds roles to concrete ``(provider, model, params)``. Swapping the
map swaps every model at once, with no code change — which is what
docs/architecture/adr/0006-llm-model-roles.md commits us to.

Roles are independent, so **hybrid maps fall out for free**: keep routing and
embedding local (high volume, cheap, privacy-sensitive) and send only the
reasoner to a cloud API. That is likely the best production cost/quality point.
"""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from neura_llm.capabilities import LLMCapability, capabilities_for
from neura_llm.errors import RoleNotConfiguredError


class ModelRole(StrEnum):
    """What a call needs, decoupled from which model serves it."""

    ROUTER = "router"
    """Intent classification and short structured decisions. Highest volume."""

    REASONER = "reasoner"
    """Answer generation and tool selection. Where quality matters most."""

    GUARD = "guard"
    """Injection detection and groundedness verification. Fast, low false-positive."""

    EMBEDDER = "embedder"
    """Vector embeddings for retrieval."""

    SUMMARIZER = "summarizer"
    """Conversation compaction and escalation handoff notes."""


class ProviderConfig(BaseModel):
    """Where a provider lives. Any OpenAI-compatible endpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str
    base_url: str
    api_key: str = Field(default="", repr=False)
    timeout_s: float = 120.0
    is_local: bool = Field(
        default=False,
        description="Local inference costs nothing and never leaves the machine — "
        "relevant to both billing and the sovereign deployment tier.",
    )
    capabilities: frozenset[LLMCapability] | None = Field(
        default=None, description="Overrides autodetection when a deployment differs"
    )


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int | None = None
    reasoning_effort: str | None = Field(
        default=None,
        description=(
            "Default thinking budget for this role. A per-request value overrides it, "
            "so a node that genuinely wants deliberation can still ask. Values are the "
            "provider's own — see ChatRequest.reasoning_effort."
        ),
    )
    dimensions: int | None = Field(
        default=None,
        description=(
            "EMBEDDER only. Vectors of different sizes are NOT comparable; this is "
            "recorded so a mismatch fails loudly instead of degrading retrieval silently."
        ),
    )


class RoleMap(BaseModel):
    """A complete binding of roles to models. The unit that gets swapped."""

    model_config = ConfigDict(extra="forbid")

    name: str
    providers: dict[str, ProviderConfig]
    roles: dict[ModelRole, RoleConfig]

    def resolve(self, role: ModelRole) -> tuple[ProviderConfig, RoleConfig]:
        role_config = self.roles.get(role)
        if role_config is None:
            raise RoleNotConfiguredError(
                f"Role {role.value!r} is not defined in role map {self.name!r}.",
                details={"role": role.value, "role_map": self.name},
            )
        provider = self.providers.get(role_config.provider)
        if provider is None:
            raise RoleNotConfiguredError(
                f"Role {role.value!r} references unknown provider "
                f"{role_config.provider!r} in role map {self.name!r}.",
                details={"provider": role_config.provider, "role_map": self.name},
            )

        # Catch an unconfigured provider HERE, with an actionable message, rather
        # than letting it surface later as a confusing "could not reach cloud at ."
        # network error. A missing environment variable is a setup problem, and
        # should read like one.
        missing = [
            name
            for name, value in (
                (f"{role_config.provider.upper()}_LLM_BASE_URL", provider.base_url),
                (f"CLOUD_MODEL_{role.value.upper()}", role_config.model),
            )
            if not value
        ]
        if missing:
            raise RoleNotConfiguredError(
                f"Role map {self.name!r} needs configuration for role {role.value!r}: "
                f"{', '.join(missing)} not set. "
                f"See .env.example, or use NEURA_ROLE_MAP=ollama-dev to stay fully local.",
                details={
                    "role": role.value,
                    "role_map": self.name,
                    "missing_env_vars": missing,
                },
            )

        return provider, role_config

    def capabilities(self, role: ModelRole) -> frozenset[LLMCapability]:
        provider, role_config = self.resolve(role)
        if provider.capabilities is not None:
            return provider.capabilities
        return capabilities_for(provider_name=provider.name, model=role_config.model)

    @property
    def embedding_model(self) -> str:
        _, role_config = self.resolve(ModelRole.EMBEDDER)
        return role_config.model

    @property
    def is_fully_local(self) -> bool:
        """True when no call leaves the machine — the sovereign deployment property."""
        return all(
            self.providers[rc.provider].is_local
            for rc in self.roles.values()
            if rc.provider in self.providers
        )


# ── Built-in role maps ───────────────────────────────────────────────────────


def _ollama_provider() -> ProviderConfig:
    return ProviderConfig(
        name="ollama",
        # Ollama's OpenAI-compatible endpoint. The api_key is required by the
        # client library and ignored by Ollama.
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        timeout_s=float(os.getenv("OLLAMA_TIMEOUT_S", "180")),
        is_local=True,
    )


def ollama_dev() -> RoleMap:
    """Development and the sovereign tier. Zero cost, everything on this machine.

    Model choices reflect what each role needs: a 3B model is plenty for
    classification and is far faster, while generation gets the largest model
    that still answers in a time a shopper would tolerate.

    **Every model is overridable by environment variable.** Comparing two models
    for one role is the single most common experiment here, and it should not
    require editing this file — a role map you have to edit to test is a role map
    people test by not testing. Defaults are what the measurements below chose;
    an override is how the next measurement gets made.

    `REASONER` is `qwen3:8b`, measured against `qwen3.5:9b` and `llama3.1:8b`
    on 2026-07-29: identical tool selection (5/5) at roughly **half** the
    latency of the 9B, and a grounded draft of the same quality. `llama3.1:8b`
    was faster still and got 4/5 — it routed a delivery-cost question to product
    search, which is the kind of error that produces a confidently wrong answer
    rather than a slow one.

    Both Qwen models *think* by default, spending the token budget on reasoning
    before emitting any content. Callers that want an answer rather than
    deliberation pass `reasoning_effort="none"`; see `ChatRequest`.
    """
    return RoleMap(
        name="ollama-dev",
        providers={"ollama": _ollama_provider()},
        roles={
            ModelRole.ROUTER: RoleConfig(
                provider="ollama",
                model=os.getenv("OLLAMA_MODEL_ROUTER", "llama3.2:3b"),
                temperature=0.0,
            ),
            ModelRole.REASONER: RoleConfig(
                provider="ollama",
                model=os.getenv("OLLAMA_MODEL_REASONER", "qwen3:8b"),
                temperature=0.3,
            ),
            ModelRole.GUARD: RoleConfig(
                provider="ollama",
                model=os.getenv("OLLAMA_MODEL_GUARD", "llama3.2:3b"),
                temperature=0.0,
            ),
            ModelRole.EMBEDDER: RoleConfig(
                provider="ollama",
                # Changing this is a REINDEX, not a config edit — vectors from
                # two models are not comparable and mixing them degrades
                # retrieval with no error (llm-abstraction.md §5.2).
                model=os.getenv("OLLAMA_MODEL_EMBEDDER", "nomic-embed-text"),
                dimensions=768,
            ),
            ModelRole.SUMMARIZER: RoleConfig(
                provider="ollama",
                model=os.getenv("OLLAMA_MODEL_SUMMARIZER", "llama3.1:8b"),
                temperature=0.3,
            ),
        },
    )


def cloud_prod() -> RoleMap:
    """Production. Models come from environment variables.

    Deliberately not hard-coded: which cloud model to use is decided by eval
    results and pricing at the time of the swap, not months in advance
    (docs/open-questions.md L1).
    """
    return RoleMap(
        name="cloud-prod",
        providers={
            "cloud": ProviderConfig(
                name="cloud",
                base_url=os.getenv("CLOUD_LLM_BASE_URL", ""),
                api_key=os.getenv("CLOUD_LLM_API_KEY", ""),
                is_local=False,
            )
        },
        roles={
            ModelRole.ROUTER: RoleConfig(
                provider="cloud", model=os.getenv("CLOUD_MODEL_ROUTER", ""), temperature=0.0
            ),
            ModelRole.REASONER: RoleConfig(
                provider="cloud", model=os.getenv("CLOUD_MODEL_REASONER", ""), temperature=0.3
            ),
            ModelRole.GUARD: RoleConfig(
                provider="cloud", model=os.getenv("CLOUD_MODEL_GUARD", ""), temperature=0.0
            ),
            ModelRole.EMBEDDER: RoleConfig(
                provider="cloud",
                model=os.getenv("CLOUD_MODEL_EMBEDDER", ""),
                dimensions=int(os.getenv("CLOUD_EMBEDDING_DIMENSIONS", "1536")),
            ),
            ModelRole.SUMMARIZER: RoleConfig(
                provider="cloud", model=os.getenv("CLOUD_MODEL_SUMMARIZER", ""), temperature=0.3
            ),
        },
    )


def hybrid() -> RoleMap:
    """Local for the cheap, high-volume roles; cloud only for reasoning.

    Often the best cost/quality point in production, and it keeps embeddings —
    which see every product and every customer message — on our own machines.
    """
    base = cloud_prod()
    return RoleMap(
        name="hybrid",
        providers={"ollama": _ollama_provider(), "cloud": base.providers["cloud"]},
        roles={
            ModelRole.ROUTER: RoleConfig(provider="ollama", model="llama3.2:3b", temperature=0.0),
            ModelRole.GUARD: RoleConfig(provider="ollama", model="llama3.2:3b", temperature=0.0),
            ModelRole.EMBEDDER: RoleConfig(
                provider="ollama", model="nomic-embed-text", dimensions=768
            ),
            ModelRole.REASONER: base.roles[ModelRole.REASONER],
            ModelRole.SUMMARIZER: base.roles[ModelRole.SUMMARIZER],
        },
    )


def sovereign() -> RoleMap:
    """Customer-hosted. Identical to development, pointed at their inference host.

    Not a dev mode — a shipping product tier
    (docs/business/blueprint-v2.md §4.3).
    """
    role_map = ollama_dev()
    return RoleMap(name="sovereign", providers=role_map.providers, roles=role_map.roles)


BUILTIN_ROLE_MAPS = {
    "ollama-dev": ollama_dev,
    "cloud-prod": cloud_prod,
    "hybrid": hybrid,
    "sovereign": sovereign,
}


def load_role_map(name: str) -> RoleMap:
    factory = BUILTIN_ROLE_MAPS.get(name)
    if factory is None:
        raise RoleNotConfiguredError(
            f"Unknown role map {name!r}. Available: {sorted(BUILTIN_ROLE_MAPS)}",
            details={"requested": name, "available": sorted(BUILTIN_ROLE_MAPS)},
        )
    return factory()
