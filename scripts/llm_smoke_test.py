#!/usr/bin/env python3
"""Prove the LLM layer really works against real models.

Unit tests use fakes, so they cannot tell you whether Ollama is running, whether
the models are pulled, or whether this particular model can actually hold to a
JSON schema. This does.

    make llm-check                       # uses NEURA_ROLE_MAP, default ollama-dev
    uv run python scripts/llm_smoke_test.py --role-map hybrid
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Literal

from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from neura_core import load_env
from neura_llm import (
    ChatRequest,
    LLMCapability,
    LLMClient,
    Message,
    ModelRole,
    RoleNotConfiguredError,
    ToolSpec,
)

console = Console()


class IntentDecision(BaseModel):
    """A realistic structured-output test — this is close to what the router does."""

    intent: Literal["order_status", "product_qa", "policy_qa", "out_of_scope"]
    confidence: float = Field(ge=0.0, le=1.0)
    order_reference: str | None = None


async def _check_chat(client: LLMClient) -> tuple[bool, str]:
    response = await client.chat(
        ModelRole.ROUTER,
        ChatRequest(
            messages=[
                Message.system("Reply with exactly one word."),
                Message.user("Say the word: ready"),
            ],
            max_tokens=20,
        ),
    )
    text = response.content.strip()
    return bool(
        text
    ), f"{text[:40]!r} · {response.latency_ms}ms · {response.usage.total_tokens} tokens"


async def _check_structured(client: LLMClient) -> tuple[bool, str]:
    """The hard one. Small models are much weaker at holding to a schema."""
    result = await client.chat_structured(
        ModelRole.ROUTER,
        ChatRequest(
            messages=[
                Message.system(
                    "Classify the customer message into an intent. "
                    "Extract the order number if one is mentioned."
                ),
                Message.user("hey where is my order 1001?? it's been a week"),
            ]
        ),
        IntentDecision,
    )
    value = result.value
    correct = value.intent == "order_status"
    detail = (
        f"intent={value.intent} order_ref={value.order_reference} · {result.attempts} attempt(s)"
    )
    if not correct:
        detail += "  [yellow](expected order_status)[/]"
    return correct, detail


async def _check_embeddings(client: LLMClient) -> tuple[bool, str]:
    result = await client.embed(["a cast iron skillet", "a frying pan"])
    if len(result.vectors) != 2:
        return False, f"expected 2 vectors, got {len(result.vectors)}"

    # Similar sentences should be closer than unrelated ones. If this fails, the
    # embedding model is not doing anything useful and retrieval will be noise.
    a, b = result.vectors
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    similarity = dot / norm if norm else 0.0
    return similarity > 0.5, f"{result.dimensions} dimensions · similarity {similarity:.3f}"


async def _check_tool_calling(client: LLMClient) -> tuple[bool, str]:
    caps = client.capabilities(ModelRole.REASONER)
    if LLMCapability.NATIVE_TOOL_CALLING not in caps:
        return True, "not supported by this model — the fallback path would be used"

    response = await client.chat(
        ModelRole.REASONER,
        ChatRequest(
            messages=[Message.user("What is the status of order 1001?")],
            tools=[
                ToolSpec(
                    name="get_order_status",
                    description="Look up the status of one order.",
                    parameters={
                        "type": "object",
                        "properties": {"order_ref": {"type": "string"}},
                        "required": ["order_ref"],
                    },
                )
            ],
        ),
    )
    if not response.tool_calls:
        return False, "model did not request the tool"
    call = response.tool_calls[0]
    return call.name == "get_order_status", f"called {call.name}({call.arguments})"


async def run(role_map: str) -> int:
    console.print()
    console.rule(f"[bold]LLM smoke test — role map: {role_map}")

    client = LLMClient.from_role_map_name(role_map)

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("role")
    table.add_column("model")
    table.add_column("capabilities")

    unconfigured: list[str] = []
    for role in ModelRole:
        try:
            caps = sorted(c.value for c in client.capabilities(role))
            table.add_row(role.value, client.model_for(role), ", ".join(caps) or "—")
        except RoleNotConfiguredError as exc:
            unconfigured.append(role.value)
            missing = ", ".join(exc.details.get("missing_env_vars", []))
            table.add_row(role.value, "[red]not configured[/]", f"[red]{missing or exc.message}[/]")

    console.print()
    console.print(table)

    if unconfigured:
        console.print(
            f"\n[yellow]  {len(unconfigured)} role(s) not configured: "
            f"{', '.join(unconfigured)}[/]"
            "\n  Set the variables above in .env, or use --role-map ollama-dev "
            "to stay fully local.\n"
        )
        return 1
    console.print(
        f"\n  fully local: {'yes' if client.is_fully_local else 'no'}"
        f"  ·  embedding namespace: {client.embedding_model}\n"
    )

    checks = (
        ("chat", _check_chat),
        ("structured output", _check_structured),
        ("embeddings", _check_embeddings),
        ("tool calling", _check_tool_calling),
    )

    failures = 0
    for label, check in checks:
        try:
            ok, detail = await check(client)
        except Exception as exc:
            ok, detail = False, f"[red]{type(exc).__name__}: {exc}[/]"
        mark = "[green]✔[/]" if ok else "[red]✘[/]"
        console.print(f"  {mark} {label:<20} {detail}")
        failures += 0 if ok else 1

    console.print()
    if failures:
        console.print(f"[red]{failures} check(s) failed.[/]\n")
        return 1
    console.print("[green]All checks passed. The LLM layer is working.[/]\n")
    return 0


def main() -> None:
    # Role maps read OLLAMA_* and CLOUD_* with os.getenv, which cannot see a
    # .env file nobody loaded.
    load_env()
    parser = argparse.ArgumentParser(description="Verify the LLM layer against real models.")
    parser.add_argument(
        "--role-map",
        default=os.getenv("NEURA_ROLE_MAP", "ollama-dev"),
        help="ollama-dev | cloud-prod | hybrid | sovereign",
    )
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(run(args.role_map)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
