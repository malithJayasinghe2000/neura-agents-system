"""Measuring the dispatcher — [ADR-0031] §6.

The harness resolves targets and datasets through the ``neura.eval_targets``
entry point, and finds ``datasets/`` beside the module the factory lives in. That
mechanism never required a target to be an *agent*; only the convention of
keeping datasets inside agent packages did. So this registers exactly as CARE and
SELL do, and the cases live next door.

**There is no dispatcher yet, and this reports that rather than hiding it.**
:class:`DispatchTarget` returns ``not_run`` for every case, so a run against it
is *unmeasured* rather than a plausible-looking zero — the same distinction
``NotImplementedTarget`` exists to preserve, and the same one that stopped a dead
Ollama being read as a total agent collapse on 2026-07-31 (open question E6).

When the dispatcher is built, this is the only file that changes: it stops
returning ``not_run`` and starts setting ``dispatched_to``.
"""

from __future__ import annotations

from typing import Any

from neura_evals.dataset import EvalCase
from neura_evals.target import AgentResponse

#: Why every case is currently unmeasured. Phrased as a sentence a reader of a
#: report will understand without opening this file.
NOT_BUILT = (
    "No dispatcher exists yet — ADR-0031 is decided and step 3 is unbuilt. "
    "This is not a result: the cases and the scoring are being validated, not "
    "the dispatcher."
)


class DispatchTarget:
    """The seam ADR-0031's dispatcher will fill.

    It is deliberately not a stub that *guesses*. A target returning, say, the
    first enabled agent would produce a real-looking accuracy figure derived from
    nothing, and somebody would quote it. Returning ``not_run`` cannot be quoted.
    """

    name = "dispatch"

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    async def run(self, case: EvalCase) -> AgentResponse:
        return AgentResponse(reply="", not_run=True, error=NOT_BUILT)


def build_target(llm: Any = None) -> DispatchTarget:
    """Factory, matching the signature the harness resolves entry points to."""
    return DispatchTarget(llm)


__all__ = ["NOT_BUILT", "DispatchTarget", "build_target"]
