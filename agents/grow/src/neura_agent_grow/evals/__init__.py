"""GROW's evaluation: the golden dataset and the target (Rule 4).

    datasets/gaps.yaml       one exchange per case, and what the night check must find
    datasets/calendar.yaml   one date per case, and what a campaign plan must hold (ADR-0072 §9)
    target.py                the real prompt, model and checks, behind `EvalTarget`
    calendar.py              how a calendar case runs (tagged `calendar`)

**Every case here is synthetic.** No real shop's chat has been read by this
check yet (open question E1's condition, as for CARE and SELL).
"""

from pathlib import Path

from neura_agent_grow.evals.target import GrowTarget, build_target, exchange_from

DATASET_DIR = Path(__file__).resolve().parent / "datasets"

__all__ = ["DATASET_DIR", "GrowTarget", "build_target", "exchange_from"]
