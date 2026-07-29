"""CARE's evaluation: the golden dataset, the store it runs against, and the target.

*"No agent ships without one"* (AGENTS.md). The dataset lives here, inside the
agent, rather than in the shared ``evals/`` package — because the cases are a
statement about *this* agent's behaviour, and they should move, version and be
reviewed alongside the code that produces it.

The harness stays ignorant of which agents exist. It finds both the datasets and
the target through the ``neura.eval_targets`` entry point, the same mechanism the
API uses to discover agents at startup, and for the same reason: agent #2 must
not require an edit to anything shared.

    datasets/   the golden cases, in YAML, reviewable by a support person
    fixtures/   the store those cases run against, pinned so a run is repeatable
    store.py    a commerce store made of fixture files
    target.py   CARE, wired into the harness's `EvalTarget` seam

**Every case here is synthetic**, and the harness refuses to call a fully
synthetic run "validation". That is not a defect to fix in code — it is open
question E1, and the fix is a design partner with real tickets.
"""

from pathlib import Path

from neura_agent_care.evals.store import FixtureStore, load_store
from neura_agent_care.evals.target import CareTarget, build_target

#: Where this agent's golden datasets live. Read by the eval CLI through the
#: entry point, so the harness never hardcodes a path inside an agent.
DATASET_DIR = Path(__file__).resolve().parent / "datasets"

__all__ = ["DATASET_DIR", "CareTarget", "FixtureStore", "build_target", "load_store"]
