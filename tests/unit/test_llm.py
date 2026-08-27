"""LLM layer tests.

Fakes throughout — these verify our logic, not a model's behaviour. Whether a
real model can hold to a schema is answered by ``make llm-check``, which talks to
actual Ollama.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from neura_llm import (
    ChatRequest,
    ChatResponse,
    EmbeddingDimensionMismatchError,
    EmbeddingResult,
    LLMCapability,
    LLMClient,
    Message,
    ModelRole,
    PriceTable,
    RoleNotConfiguredError,
    StructuredOutputError,
    Usage,
    capabilities_for,
    load_role_map,
)
from neura_llm.roles import ProviderConfig, RoleConfig, RoleMap
from neura_llm.structured import generate_structured


class Decision(BaseModel):
    intent: str
    confidence: float


class FakeProvider:
    """Replays scripted responses and records what it was asked."""

    def __init__(self, responses: list[ChatResponse] | None = None, *, dimensions: int = 768):
        self.name = "fake"
        self.is_local = True
        self._responses = responses or []
        self._dimensions = dimensions
        self.calls: list[dict[str, Any]] = []

    async def chat(self, request: ChatRequest, *, model: str, **kwargs: Any) -> ChatResponse:
        self.calls.append({"request": request, "model": model, "kwargs": kwargs})
        if not self._responses:
            return ChatResponse(content="ok", model=model, provider=self.name)
        return self._responses.pop(0)

    async def embed(self, texts: list[str], *, model: str) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.1] * self._dimensions for _ in texts],
            model=model,
            dimensions=self._dimensions,
        )


def _fake_role_map(*, dimensions: int = 768) -> RoleMap:
    return RoleMap(
        name="fake",
        providers={"fake": ProviderConfig(name="fake", base_url="http://x/v1", is_local=True)},
        roles={
            ModelRole.ROUTER: RoleConfig(provider="fake", model="fake-small", temperature=0.0),
            ModelRole.REASONER: RoleConfig(provider="fake", model="fake-big", temperature=0.7),
            ModelRole.EMBEDDER: RoleConfig(
                provider="fake", model="fake-embed", dimensions=dimensions
            ),
        },
    )


class TestRoleMaps:
    def test_builtin_maps_all_load(self) -> None:
        for name in ("ollama-dev", "cloud-prod", "hybrid", "sovereign"):
            assert load_role_map(name).name == name

    def test_unknown_map_lists_the_alternatives(self) -> None:
        with pytest.raises(RoleNotConfiguredError, match="Unknown role map"):
            load_role_map("nope")

    def test_ollama_dev_is_fully_local(self) -> None:
        """The property the sovereign product tier depends on."""
        assert load_role_map("ollama-dev").is_fully_local

    def test_hybrid_is_not_fully_local(self) -> None:
        """Hybrid sends the reasoner to a cloud API, so it is not sovereign."""
        assert not load_role_map("hybrid").is_fully_local

    def test_hybrid_keeps_high_volume_roles_local(self) -> None:
        """Routing, guarding and embedding see every message — keep them in-house."""
        role_map = load_role_map("hybrid")
        for role in (ModelRole.ROUTER, ModelRole.GUARD, ModelRole.EMBEDDER):
            provider, _ = role_map.resolve(role)
            assert provider.is_local, role

    def test_every_local_map_verifies_with_the_same_model(self) -> None:
        """The verifier is chosen once (ADR-0018) and must not be named twice.

        `hybrid` used to name its own `GUARD` model, so it kept `llama3.2:3b`
        after A10 measured that model calling an invented delivery date and a
        contradicted order status "grounded" 10/10. A decision written in two
        places is a decision that gets made in one of them.
        """
        guard_models = {
            name: load_role_map(name).resolve(ModelRole.GUARD)[1].model
            for name in ("ollama-dev", "sovereign", "hybrid")
        }
        assert len(set(guard_models.values())) == 1, guard_models

    def test_missing_role_is_a_clear_error(self) -> None:
        role_map = RoleMap(
            name="partial",
            providers={"p": ProviderConfig(name="p", base_url="http://x")},
            roles={ModelRole.ROUTER: RoleConfig(provider="p", model="m")},
        )
        with pytest.raises(RoleNotConfiguredError, match="reasoner"):
            role_map.resolve(ModelRole.REASONER)

    def test_role_referencing_an_unknown_provider_is_caught(self) -> None:
        role_map = RoleMap(
            name="broken",
            providers={"p": ProviderConfig(name="p", base_url="http://x")},
            roles={ModelRole.ROUTER: RoleConfig(provider="missing", model="m")},
        )
        with pytest.raises(RoleNotConfiguredError, match="unknown provider"):
            role_map.resolve(ModelRole.ROUTER)

    def test_unconfigured_provider_names_the_missing_env_vars(self) -> None:
        """A missing setting must read as a setup problem, not a network failure.

        Without this, an unset CLOUD_LLM_BASE_URL surfaced much later as
        "could not reach cloud at ." — technically true, useless to act on.
        """
        role_map = RoleMap(
            name="cloud-ish",
            providers={"cloud": ProviderConfig(name="cloud", base_url="")},
            roles={ModelRole.REASONER: RoleConfig(provider="cloud", model="")},
        )
        with pytest.raises(RoleNotConfiguredError) as exc:
            role_map.resolve(ModelRole.REASONER)

        missing = exc.value.details["missing_env_vars"]
        assert "CLOUD_LLM_BASE_URL" in missing
        assert "CLOUD_MODEL_REASONER" in missing
        # And it must point somewhere useful.
        assert "ollama-dev" in exc.value.message

    def test_fully_configured_provider_resolves(self) -> None:
        role_map = RoleMap(
            name="ok",
            providers={"cloud": ProviderConfig(name="cloud", base_url="https://x/v1")},
            roles={ModelRole.REASONER: RoleConfig(provider="cloud", model="a-model")},
        )
        provider, config = role_map.resolve(ModelRole.REASONER)
        assert provider.base_url == "https://x/v1"
        assert config.model == "a-model"


class TestCapabilities:
    def test_ollama_declares_schema_mode(self) -> None:
        """Constrained decoding is what makes the local path viable at all."""
        caps = capabilities_for(provider_name="ollama", model="llama3.2:3b")
        assert LLMCapability.JSON_SCHEMA_MODE in caps

    def test_known_local_families_get_tool_calling(self) -> None:
        caps = capabilities_for(provider_name="ollama", model="qwen3.5:9b")
        assert LLMCapability.NATIVE_TOOL_CALLING in caps

    def test_embedding_model_does_not_claim_tool_calling(self) -> None:
        caps = capabilities_for(provider_name="ollama", model="nomic-embed-text")
        assert LLMCapability.NATIVE_TOOL_CALLING not in caps

    def test_unknown_provider_assumes_modern_cloud_features(self) -> None:
        caps = capabilities_for(provider_name="somecloud", model="whatever")
        assert LLMCapability.NATIVE_TOOL_CALLING in caps


class TestReasoningEffortIsDeclared:
    def test_ollama_accepts_none(self) -> None:
        caps = capabilities_for(provider_name="ollama", model="qwen3:8b")
        assert LLMCapability.REASONING_EFFORT_NONE in caps

    def test_a_cloud_endpoint_is_assumed_not_to(self) -> None:
        """Conservative on purpose. Wrong this way costs one notch of extra
        thinking; wrong the other way 400s every affected call."""
        caps = capabilities_for(provider_name="cloud", model="gemini-3.6-flash")
        assert LLMCapability.REASONING_EFFORT_NONE not in caps


class TestPricing:
    def test_local_inference_is_free(self) -> None:
        table = PriceTable({"m": {"input": Decimal("1"), "output": Decimal("2")}})
        usage = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
        assert table.cost(model="m", usage=usage, is_local=True) == Decimal("0")

    def test_cloud_cost_is_per_million_tokens(self) -> None:
        table = PriceTable({"m": {"input": Decimal("3"), "output": Decimal("15")}})
        usage = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
        assert table.cost(model="m", usage=usage, is_local=False) == Decimal("18")

    def test_unknown_model_costs_zero_rather_than_guessing(self) -> None:
        """Reporting an unknown cost as 0 is honest; a guess corrupts the margin model."""
        table = PriceTable({})
        usage = Usage(prompt_tokens=1000, completion_tokens=1000)
        assert table.cost(model="mystery", usage=usage, is_local=False) == Decimal("0")


class TestStructuredOutput:
    async def test_schema_mode_is_used_when_available(self) -> None:
        provider = FakeProvider([ChatResponse(content='{"intent":"a","confidence":0.9}')])
        result = await generate_structured(
            provider,  # type: ignore[arg-type]
            ChatRequest(messages=[Message.user("x")]),
            Decision,
            model="m",
            capabilities=frozenset({LLMCapability.JSON_SCHEMA_MODE}),
        )
        assert result.value.intent == "a"
        assert result.attempts == 1
        assert provider.calls[0]["kwargs"]["response_format"]["type"] == "json_schema"

    async def test_json_mode_used_when_schema_mode_unavailable(self) -> None:
        provider = FakeProvider([ChatResponse(content='{"intent":"a","confidence":0.9}')])
        await generate_structured(
            provider,  # type: ignore[arg-type]
            ChatRequest(messages=[Message.user("x")]),
            Decision,
            model="m",
            capabilities=frozenset({LLMCapability.JSON_MODE}),
        )
        assert provider.calls[0]["kwargs"]["response_format"]["type"] == "json_object"

    async def test_no_capabilities_falls_back_to_prompt_only(self) -> None:
        provider = FakeProvider([ChatResponse(content='{"intent":"a","confidence":0.9}')])
        await generate_structured(
            provider,  # type: ignore[arg-type]
            ChatRequest(messages=[Message.user("x")]),
            Decision,
            model="m",
            capabilities=frozenset(),
        )
        assert "response_format" not in provider.calls[0]["kwargs"]

    async def test_repair_loop_recovers_from_invalid_output(self) -> None:
        """The realistic small-model failure: right idea, wrong shape."""
        provider = FakeProvider(
            [
                ChatResponse(content="not json at all"),
                ChatResponse(content='{"intent":"fixed","confidence":0.5}'),
            ]
        )
        result = await generate_structured(
            provider,  # type: ignore[arg-type]
            ChatRequest(messages=[Message.user("x")]),
            Decision,
            model="m",
            capabilities=frozenset({LLMCapability.JSON_MODE}),
        )
        assert result.value.intent == "fixed"
        assert result.attempts == 2
        assert result.needed_repair
        assert result.response.structured_repairs == 1

    async def test_validation_error_is_fed_back_verbatim(self) -> None:
        """Models correct far better from a concrete error than a restated instruction."""
        provider = FakeProvider(
            [
                ChatResponse(content='{"intent":"a"}'),  # missing confidence
                ChatResponse(content='{"intent":"a","confidence":0.1}'),
            ]
        )
        await generate_structured(
            provider,  # type: ignore[arg-type]
            ChatRequest(messages=[Message.user("x")]),
            Decision,
            model="m",
            capabilities=frozenset({LLMCapability.JSON_MODE}),
        )
        repair_messages = provider.calls[1]["request"].messages
        assert any("confidence" in m.content for m in repair_messages)

    async def test_gives_up_after_the_repair_budget(self) -> None:
        provider = FakeProvider([ChatResponse(content="garbage") for _ in range(5)])
        with pytest.raises(StructuredOutputError) as exc:
            await generate_structured(
                provider,  # type: ignore[arg-type]
                ChatRequest(messages=[Message.user("x")]),
                Decision,
                model="m",
                capabilities=frozenset({LLMCapability.JSON_MODE}),
            )
        assert exc.value.details["attempts"] == 3

    async def test_fenced_json_is_extracted(self) -> None:
        provider = FakeProvider(
            [ChatResponse(content='```json\n{"intent":"a","confidence":0.9}\n```')]
        )
        result = await generate_structured(
            provider,  # type: ignore[arg-type]
            ChatRequest(messages=[Message.user("x")]),
            Decision,
            model="m",
            capabilities=frozenset(),
        )
        assert result.value.intent == "a"

    async def test_json_surrounded_by_prose_is_extracted(self) -> None:
        provider = FakeProvider(
            [ChatResponse(content='Sure! {"intent":"a","confidence":0.9} Hope that helps.')]
        )
        result = await generate_structured(
            provider,  # type: ignore[arg-type]
            ChatRequest(messages=[Message.user("x")]),
            Decision,
            model="m",
            capabilities=frozenset(),
        )
        assert result.value.intent == "a"


class TestLLMClient:
    async def test_role_temperature_is_applied(self) -> None:
        client = LLMClient(_fake_role_map())
        provider = FakeProvider()
        client._providers["fake"] = provider  # type: ignore[assignment]

        await client.chat(ModelRole.REASONER, ChatRequest(messages=[Message.user("x")]))
        assert provider.calls[0]["request"].temperature == 0.7
        assert provider.calls[0]["model"] == "fake-big"

    async def test_explicit_temperature_wins_over_the_role_default(self) -> None:
        client = LLMClient(_fake_role_map())
        provider = FakeProvider()
        client._providers["fake"] = provider  # type: ignore[assignment]

        await client.chat(
            ModelRole.REASONER, ChatRequest(messages=[Message.user("x")], temperature=0.1)
        )
        assert provider.calls[0]["request"].temperature == 0.1

    async def test_reasoning_effort_none_is_downgraded_where_it_is_not_accepted(self) -> None:
        """Gemini's OpenAI-compatible endpoint 400s on `"none"`. Measured 2026-08-27.

        It took out every `compose` call in SELL's first cloud run — six of
        fourteen cases skipped as provider-unreachable, and no cloud measurement
        of the agent possible at all.
        """
        role_map = RoleMap(
            name="fake-cloud",
            providers={
                "fake": ProviderConfig(
                    name="fake",
                    base_url="http://x/v1",
                    is_local=False,
                    capabilities=frozenset({LLMCapability.JSON_MODE}),
                )
            },
            roles={ModelRole.REASONER: RoleConfig(provider="fake", model="m")},
        )
        client = LLMClient(role_map)
        provider = FakeProvider()
        client._providers["fake"] = provider  # type: ignore[assignment]

        await client.chat(
            ModelRole.REASONER,
            ChatRequest(messages=[Message.user("x")], reasoning_effort="none"),
        )
        assert provider.calls[0]["request"].reasoning_effort == "low"

    async def test_it_is_downgraded_and_never_dropped(self) -> None:
        """Dropping it lets the model think until `max_tokens` runs out and
        return empty content — the exact failure `"none"` exists to prevent."""
        role_map = RoleMap(
            name="fake-cloud",
            providers={
                "fake": ProviderConfig(
                    name="fake", base_url="http://x/v1", is_local=False, capabilities=frozenset()
                )
            },
            roles={ModelRole.REASONER: RoleConfig(provider="fake", model="m")},
        )
        client = LLMClient(role_map)
        provider = FakeProvider()
        client._providers["fake"] = provider  # type: ignore[assignment]

        await client.chat(
            ModelRole.REASONER,
            ChatRequest(messages=[Message.user("x")], reasoning_effort="none"),
        )
        assert provider.calls[0]["request"].reasoning_effort is not None

    async def test_a_provider_that_accepts_none_is_left_alone(self) -> None:
        """Ollama understands it, and that is the whole local path."""
        role_map = RoleMap(
            name="fake-local",
            providers={
                "fake": ProviderConfig(
                    name="fake",
                    base_url="http://x/v1",
                    is_local=True,
                    capabilities=frozenset({LLMCapability.REASONING_EFFORT_NONE}),
                )
            },
            roles={ModelRole.REASONER: RoleConfig(provider="fake", model="m")},
        )
        client = LLMClient(role_map)
        provider = FakeProvider()
        client._providers["fake"] = provider  # type: ignore[assignment]

        await client.chat(
            ModelRole.REASONER,
            ChatRequest(messages=[Message.user("x")], reasoning_effort="none"),
        )
        assert provider.calls[0]["request"].reasoning_effort == "none"

    async def test_embedding_namespace_is_the_model_name(self) -> None:
        """Vector rows are scoped by this, since models are not interchangeable."""
        assert LLMClient(_fake_role_map()).embedding_model == "fake-embed"

    async def test_dimension_mismatch_raises_instead_of_degrading_silently(self) -> None:
        """The trap this guards against produces no error, only worse retrieval."""
        client = LLMClient(_fake_role_map(dimensions=768))
        client._providers["fake"] = FakeProvider(dimensions=1536)  # type: ignore[assignment]

        with pytest.raises(EmbeddingDimensionMismatchError) as exc:
            await client.embed(["text"])
        assert exc.value.details["expected_dimensions"] == 768
        assert exc.value.details["actual_dimensions"] == 1536

    async def test_matching_dimensions_pass(self) -> None:
        client = LLMClient(_fake_role_map(dimensions=768))
        client._providers["fake"] = FakeProvider(dimensions=768)  # type: ignore[assignment]
        assert (await client.embed(["a", "b"])).dimensions == 768

    async def test_providers_are_reused_across_calls(self) -> None:
        client = LLMClient(_fake_role_map())
        client._providers["fake"] = FakeProvider()  # type: ignore[assignment]
        first = client._provider_for(ModelRole.ROUTER)[0]
        second = client._provider_for(ModelRole.REASONER)[0]
        assert first is second

    async def test_health_reports_every_role(self) -> None:
        health = await LLMClient(load_role_map("ollama-dev")).health()
        assert set(health) == {r.value for r in ModelRole}
        assert "llama3.2:3b" in health["router"]
