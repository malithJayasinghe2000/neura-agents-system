"""Measuring the dispatcher — [ADR-0031] §6.

The harness resolves targets and datasets through the ``neura.eval_targets``
entry point, and finds ``datasets/`` beside the module the factory lives in. That
mechanism never required a target to be an *agent*; only the convention of
keeping datasets inside agent packages did. So this registers exactly as CARE and
SELL do, and the cases live next door.

**What a run here measures, and what it does not.** It measures the choice: one
model call, the candidates' own declarations, one agent key out. It does not run
the chosen agent, so nothing here says whether the answer was any good — that is
the agent's own suite. A dispatch suite at 1.00 beside an agent suite at 0.40
means every message reached the right service and the service was wrong.

**No candidates means no run.** A deployment with fewer than two installed
agents cannot dispatch, and the cases are reported unmeasured rather than scored
— a suite that silently measured a one-agent shop would report a perfect
accuracy for a choice nobody made.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from neura_evals.dataset import EvalCase
from neura_evals.target import AgentResponse

from neura_dispatch.candidates import installed_candidates
from neura_dispatch.chooser import NoCandidatesError, choose

#: Why a case is unmeasured when the deployment cannot dispatch. Phrased as a
#: sentence a reader of a report understands without opening this file.
NOT_DISPATCHABLE = (
    "Fewer than two installed agents declare what they answer, so there was "
    "nothing to choose between. This is not a result."
)

#: Kept so a report can explain a run against a build with no dispatcher wired.
#: Unused now that :func:`choose` is real — retained because the eval report
#: quotes whichever error a target supplies, and deleting the constant would
#: silently change what an older run file means.
NOT_BUILT = (
    "No dispatcher exists yet — ADR-0031 is decided and step 3 is unbuilt. "
    "This is not a result: the cases and the scoring are being validated, not "
    "the dispatcher."
)

_ZERO = Decimal("0")


class DispatchTarget:
    """The chooser, wired to the harness.

    Every installed agent is a candidate. The suite deliberately does not filter
    by entitlement: it measures whether the *right* agent is chosen when all of
    them are available, and ADR-0031 §4's "the shop has not bought it" path is a
    decision made after this one, on a real tenant, with a real person at the
    end of it.
    """

    name = "dispatch"

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    async def run(self, case: EvalCase) -> AgentResponse:
        candidates = installed_candidates()
        if len(candidates) < 2:
            return AgentResponse(reply="", not_run=True, error=NOT_DISPATCHABLE)

        try:
            decision = await choose(
                self._llm,
                case.input,
                candidates,
                history=[dict(t) for t in case.session.history] or None,
            )
        except NoCandidatesError as exc:  # pragma: no cover - guarded above
            return AgentResponse(reply="", not_run=True, error=str(exc))
        except Exception as exc:
            # The provider could not be reached, or would not produce the
            # schema. **Not a result** — scoring it as a misroute would report a
            # dead model server as a broken dispatcher, which is the mistake of
            # 2026-07-31 that `infrastructure_error` exists to prevent (E6).
            return AgentResponse(reply="", infrastructure_error=f"{type(exc).__name__}: {exc}")

        return AgentResponse(
            reply="",
            dispatched_to=decision.agent,
            # The chooser calls no tools and writes no reply, so most of the
            # harness's fields are genuinely empty rather than unset. Cost and
            # calls are real and are the number ADR-0031 §7 says to watch: this
            # runs *before* the chosen agent's own router, so it is a second
            # classification on every dispatched turn.
            llm_calls=len(decision.responses),
            cost_usd=sum((r.cost_usd for r in decision.responses), start=_ZERO),
            tokens_used=sum(getattr(r, "total_tokens", 0) or 0 for r in decision.responses),
            escalation_reason=decision.reason,
        )


def build_target(llm: Any = None) -> DispatchTarget:
    """Factory, matching the signature the harness resolves entry points to."""
    return DispatchTarget(llm)


__all__ = ["NOT_BUILT", "NOT_DISPATCHABLE", "DispatchTarget", "build_target"]
