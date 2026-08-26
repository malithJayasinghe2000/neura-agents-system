"""NEURA-SELL.

Built in the order `docs/agents/sell.md` recommends: the two surfaces with no
model in them first — the feed, then MCP — because both are deterministic, both
are testable without a model server, and neither costs a single inference.

**These are tests, not evals, and that distinction is open question E8.** The
feed is a pure function of synced entities: it cannot regress in the way an eval
exists to catch, and calling its checks "an eval" would inflate the suite with
cases that can only ever pass or fail deterministically. The conversational
surface, when it exists, is graded by `make eval` like CARE's.
"""

from __future__ import annotations

import pytest

from neura_agent_sell import MANIFEST
from neura_domain import Capability


class TestManifest:
    """The identity card — what SELL needs, and what it may do."""

    def test_it_needs_both_halves_of_a_recommendation(self) -> None:
        """Search finds candidates; read expands them. Neither alone is enough.

        Required rather than optional so a merchant learns at *connection* time
        that this agent will not work for their store, instead of discovering it
        through a shopper being handed to a human.
        """
        assert MANIFEST.requires_capabilities == {
            Capability.PRODUCT_SEARCH,
            Capability.PRODUCT_READ,
        }

    def test_the_optional_capabilities_each_degrade_something_named(self) -> None:
        """Optional means the agent still runs, worse, in a way sell.md §3.3 names."""
        assert MANIFEST.optional_capabilities == {
            Capability.INVENTORY_READ,
            Capability.CATEGORY_READ,
        }

    def test_it_requires_no_capability_that_could_change_a_store(self) -> None:
        """The whole scope is read-only, on every surface (ADR-0010, ADR-0023).

        Asserted against the *enum* rather than against a list written here, so
        a capability added to `neura-domain` later is caught by this test rather
        than silently permitted by an allowlist nobody updated.
        """
        writes = {c for c in Capability if c.value.endswith(".write")}
        declared = MANIFEST.requires_capabilities | MANIFEST.optional_capabilities
        assert not (declared & writes)

    def test_the_feed_has_no_scope_because_it_has_no_key(self) -> None:
        """The point of ADR-0024, pinned.

        A crawler presents nothing, so there is no scope to check. What *is*
        scoped is switching publication on — a different and much sharper power,
        because it is close to irreversible.
        """
        assert "sell:feed:read" not in MANIFEST.scopes
        assert "sell:feed:manage" in MANIFEST.scopes

    def test_an_external_agents_key_cannot_hold_a_conversation(self) -> None:
        """`sell:mcp:connect` is deliberately not `sell:chat:write`.

        An external AI agent reading the catalogue and a shopper talking to
        SELL are different callers with different powers, and one scope for
        both would make the narrower one unexpressible.
        """
        assert {"sell:mcp:connect", "sell:chat:write"} <= MANIFEST.scopes
        assert "sell:mcp:connect" != "sell:chat:write"


class TestDiscovery:
    """How the deployable finds SELL — and what it correctly does not find yet."""

    def test_the_api_discovers_sell_without_naming_it(self) -> None:
        from neura_api.registry import discover_agents

        agents = discover_agents()
        assert "sell" in agents
        assert agents["sell"].route_prefix == "/v1/sell"

    def test_sell_has_no_runner_yet_and_that_is_the_honest_state(self) -> None:
        """`AGENT_NOT_RUNNABLE`, not a 500 and not a 404.

        The graph does not exist, so no runner is registered. A runner wired to
        a graph that is not there would mount `/v1/sell/chat` and answer every
        shopper with an exception — "we have it and it is broken" reported as
        though it were working. Absent is the true state, and the API already
        distinguishes it from "we do not have it".
        """
        from neura_api.registry import discover_runners

        assert "sell" not in discover_runners()

    def test_sell_declares_no_eval_target_yet(self) -> None:
        """No graph, nothing to grade.

        Registering a target early would let `make eval` report a suite that
        measures nothing — this project has recorded that shape of failure
        enough times to check for it.
        """
        from importlib.metadata import entry_points

        assert "sell" not in {ep.name for ep in entry_points(group="neura.eval_targets")}


@pytest.mark.parametrize("forbidden", ["bagisto", "shopify", "woocommerce", "magento"])
def test_sell_names_no_commerce_platform(forbidden: str) -> None:
    """Rule 1, checked here too rather than trusted to the CI grep alone.

    The standalone script covers the whole tree; this fails inside the suite a
    developer actually runs, where the feedback is immediate.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "agents/sell/src"
    hits = [
        str(p.relative_to(src)) for p in src.rglob("*.py") if forbidden in p.read_text().lower()
    ]
    assert not hits, f"{forbidden!r} appears in {hits}"
