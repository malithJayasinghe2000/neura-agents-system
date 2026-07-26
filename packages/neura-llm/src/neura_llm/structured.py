"""Schema-valid output from models of very different strength.

This is where a naive local→cloud abstraction breaks. An 8B model is materially
less reliable at emitting strictly schema-valid JSON than a frontier model, and
discovering that during a production swap means the swap has already failed.

Two mechanisms, per docs/architecture/llm-abstraction.md §4:

**Capability tiers** — use the strongest enforcement the provider actually
declares:

    tier 1  JSON_SCHEMA_MODE   server-side constrained decoding; malformed output
                               is impossible. Ollama supports this, which is the
                               single most important fact for the local path.
    tier 2  JSON_MODE          valid JSON guaranteed, shape validated by us
    tier 3  prompt-only        schema in the prompt, extracted from the reply

**A bounded repair loop** — even at tier 1, semantic mistakes happen (right
shape, wrong enum value). The validation error is fed back verbatim, twice, then
we give up and let the caller escalate. Every repair is counted: a rising repair
rate is the early warning that a model is a bad fit for a role, and a dashboard
is a much better place to learn that than an incident.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from neura_core import get_logger
from neura_llm.capabilities import LLMCapability
from neura_llm.errors import StructuredOutputError
from neura_llm.provider import OpenAICompatibleProvider
from neura_llm.types import ChatRequest, ChatResponse, Message

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 3
"""One initial attempt plus two repairs. Beyond this, escalation is cheaper."""


class StructuredResult[ModelT: BaseModel](BaseModel):
    """A validated object plus the cost of getting it."""

    value: ModelT
    response: ChatResponse
    attempts: int

    @property
    def needed_repair(self) -> bool:
        return self.attempts > 1


def _schema_instruction(schema: dict[str, Any]) -> str:
    return (
        "Respond with a single JSON object and nothing else. "
        "No prose, no markdown fence. It must match this JSON Schema exactly:\n"
        f"{json.dumps(schema, indent=2)}"
    )


def _extract_json(content: str) -> Any:
    """Parse JSON, tolerating a fence or surrounding prose.

    Needed at tier 3, where nothing constrains the model's formatting.
    """
    text = content.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1].removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def generate_structured[ModelT: BaseModel](
    provider: OpenAICompatibleProvider,
    request: ChatRequest,
    schema_type: type[ModelT],
    *,
    model: str,
    capabilities: frozenset[LLMCapability],
) -> StructuredResult[ModelT]:
    """Get a validated instance of ``schema_type``, repairing up to twice."""
    schema = schema_type.model_json_schema()
    messages = list(request.messages)
    kwargs: dict[str, Any] = {}

    if LLMCapability.JSON_SCHEMA_MODE in capabilities:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_type.__name__, "schema": schema, "strict": False},
        }
    elif LLMCapability.JSON_MODE in capabilities:
        kwargs["response_format"] = {"type": "json_object"}
        messages.append(Message.system(_schema_instruction(schema)))
    else:
        messages.append(Message.system(_schema_instruction(schema)))

    last_error = ""
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = None
    response: ChatResponse | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_request = request.model_copy(
            update={
                "messages": messages,
                # Final attempt goes deterministic: if creativity has not helped
                # by now, it is the problem.
                "temperature": 0.0 if attempt == MAX_ATTEMPTS else request.temperature,
            }
        )

        try:
            response = await provider.chat(attempt_request, model=model, **kwargs)
        except Exception:
            # A tier-1 request rejected by a provider that does not really
            # support schema mode: drop to a weaker tier rather than failing.
            if kwargs.get("response_format", {}).get("type") == "json_schema":
                log.warning("json_schema_mode_rejected", model=model, detail="falling back")
                kwargs["response_format"] = {"type": "json_object"}
                messages.append(Message.system(_schema_instruction(schema)))
                continue
            raise

        total_prompt_tokens += response.usage.prompt_tokens
        total_completion_tokens += response.usage.completion_tokens
        total_cost = response.cost_usd if total_cost is None else total_cost + response.cost_usd

        try:
            value = schema_type.model_validate(_extract_json(response.content))
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            log.warning(
                "structured_output_invalid",
                model=model,
                attempt=attempt,
                schema=schema_type.__name__,
            )
            if attempt < MAX_ATTEMPTS:
                # Feed the error back verbatim — models correct far better from a
                # concrete validation message than from a restated instruction.
                messages = [
                    *messages,
                    Message.assistant(response.content),
                    Message.user(
                        f"That response was not valid. The error was:\n{last_error}\n\n"
                        "Return corrected JSON only."
                    ),
                ]
            continue

        response.usage.prompt_tokens = total_prompt_tokens
        response.usage.completion_tokens = total_completion_tokens
        response.cost_usd = total_cost or response.cost_usd
        response.structured_repairs = attempt - 1

        if attempt > 1:
            log.info("structured_output_repaired", model=model, attempts=attempt)

        return StructuredResult[ModelT](value=value, response=response, attempts=attempt)

    raise StructuredOutputError(
        f"{model} could not produce valid {schema_type.__name__} in {MAX_ATTEMPTS} attempts.",
        details={
            "model": model,
            "schema": schema_type.__name__,
            "attempts": MAX_ATTEMPTS,
            "last_error": last_error[:500],
        },
    )
