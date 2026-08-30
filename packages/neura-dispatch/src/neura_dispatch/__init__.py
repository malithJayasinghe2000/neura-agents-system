"""Choosing which agent answers a shopper's message — [ADR-0031].

A merchant who buys two agents can currently only be delivered one: the agent is
fixed in their HTML by ``data-neura-agent``, and the widget refuses to mount a
second box. This package is where that gets fixed, and the shape of the fix is
fixed by the ADR:

    The shopper never chooses. The server does, by reading what each of the
    merchant's *enabled* agents declares it handles.

**It must never learn an agent's name.** ``neura-api``'s ``routes/agent.py`` does
not know the word "care" — ``/v1/care/chat`` exists because CARE's manifest says
so — and a dispatcher containing ``if the question is about products -> sell``
would put agent names in shared code, which is the same failure as a commerce
platform named outside ``neura-adapters``. So the agents declare
(``AgentManifest.handles`` and ``.handles_examples``) and this reads
declarations.

**Order of construction, deliberately.** The eval target and its dataset exist
here *before* the dispatcher does. That is not an accident and not a placeholder
habit: milestone 1.4 built the whole eval harness before any agent existed, for
the reason recorded in ``neura_evals.target`` — a thing measured only after it is
written gets the measurement its author expected. ADR-0031 §6 requires a gate
before the dispatcher ships, and a gate needs a baseline taken on cases nobody
wrote to pass.
"""

from __future__ import annotations

__all__: list[str] = []
