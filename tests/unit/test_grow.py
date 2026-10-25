"""NEURA-GROW, the first assistant with no chat (ADR-0064, docs/agents/grow.md).

GROW's first surface is a nightly job and a dashboard page: no shopper ever
talks to it. It is installed and discovered like every agent, so FiveNeurals can
tick it for a shop (R46), but **nothing that serves shoppers may offer it a
message**: the dispatcher must not choose it, and the API must not mount a chat
for it that could only ever answer *not runnable*.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from structlog.testing import capture_logs

from neura_dispatch.candidates import installed_candidates


def _grow_manifest():  # type: ignore[no-untyped-def]
    found = [ep for ep in entry_points(group="neura.agents") if ep.name == "grow"]
    assert found, "GROW is not installed as an agent"
    return found[0].load()


def test_grow_is_installed_as_an_agent() -> None:
    manifest = _grow_manifest()
    assert manifest.key == "grow"
    assert manifest.name == "NEURA-GROW"


def test_grow_says_it_has_no_chat() -> None:
    assert _grow_manifest().chat is False


def test_the_dispatcher_never_offers_grow_a_message() -> None:
    """Left out on purpose, not skipped as broken: no "declares nothing" warning."""
    with capture_logs() as logs:
        keys = {c.key for c in installed_candidates()}
    assert "grow" not in keys
    assert {"care", "sell"} <= keys
    assert not [e for e in logs if e.get("event") == "dispatch_candidate_declares_nothing"]


def test_the_api_mounts_no_chat_for_grow() -> None:
    """The mounting step itself, run on a fresh app with every installed agent."""
    from fastapi import FastAPI

    from neura_api.main import _mount_agents
    from neura_api.registry import discover_agents

    app = FastAPI()
    app.state.agents = discover_agents()
    assert "grow" in app.state.agents
    _mount_agents(app)
    paths = set(app.openapi()["paths"])
    assert not [p for p in paths if p.startswith("/v1/grow")]
    assert "/v1/care/chat" in paths
