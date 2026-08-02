"""The guard — injection detection and PII redaction, both without a model.

Two independent jobs that happen at the same moment in a turn, and are kept in
separate modules because they answer to different documents and fail in
different directions:

* :mod:`~neura_agent_core.guard.injection` — recognise the attacks we can name,
  so an obvious one costs a log line rather than a support person (ADR-0012,
  open question S4). It is **not** the defence against injection; the structural
  argument in security-model.md §2.1 is, and `make eval-guard-off` proves it
  still holds with every rule here switched off (ADR-0011).
* :mod:`~neura_agent_core.guard.pii` — replace personal data with reversible
  tokens before anything reaches a model, and put it back on the way out
  (security-model.md §6.1).

Neither contains a model, a score or a threshold. That is the decision in
ADR-0011 and it is the reason open question S1 — "the classifier needs a tuned
threshold and there is nothing to tune it against" — does not apply to what
shipped.
"""

from neura_agent_core.guard.injection import RULES, Rule, Verdict, normalise, scan
from neura_agent_core.guard.pii import TOKEN_RE, Leak, PiiVault, find_leaks

__all__ = [
    "RULES",
    "TOKEN_RE",
    "Leak",
    "PiiVault",
    "Rule",
    "Verdict",
    "find_leaks",
    "normalise",
    "scan",
]
