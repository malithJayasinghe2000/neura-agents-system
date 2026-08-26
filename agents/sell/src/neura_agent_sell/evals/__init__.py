"""SELL's evaluation: the golden dataset, the store it runs against, and the target.

*"No agent ships without one"* (AGENTS.md). The dataset lives here, inside the
agent, rather than in the shared ``evals/`` package — the cases are a statement
about *this* agent's behaviour and should move, version and be reviewed
alongside the code that produces it.

The harness stays ignorant of which agents exist. It finds both the datasets and
the target through the ``neura.eval_targets`` entry point, the same mechanism
the API uses to discover agents at startup, and for the same reason.

    datasets/   the golden cases, in YAML, reviewable by a non-engineer
    fixtures/   the catalogue those cases run against, pinned so a run repeats
    store.py    a commerce store made of fixture files — catalogue only
    target.py   SELL, wired into the harness's `EvalTarget` seam

**Every case here is synthetic**, and the harness refuses to call a fully
synthetic run "validation". That is not a defect to fix in code — it is open
question **E1**, and the fix is a design partner with real shoppers asking real
questions.
"""

from pathlib import Path

from neura_agent_sell.evals.store import ALL_CAPABILITIES, FixtureStore, load_store
from neura_agent_sell.evals.target import SellTarget, build_target

#: Where this agent's golden datasets live. Read by the eval CLI through the
#: entry point, so the harness never hardcodes a path inside an agent.
DATASET_DIR = Path(__file__).resolve().parent / "datasets"

__all__ = [
    "ALL_CAPABILITIES",
    "DATASET_DIR",
    "FixtureStore",
    "SellTarget",
    "build_target",
    "load_store",
]
