"""The ``sign_in`` node: an order question from someone not signed in. ADR-0057 §7.

The chat box cannot say who a shopper is unless the shop's server signed a pass
for them. Without one, an order question cannot be answered here, and it is
**not a handover** either: a person could not answer it without knowing who is
asking. So the turn ends with the owner's sentence: sign in, or contact the shop.

Fixed text, never the model's. This node says the no-details form; the turn
service puts on the shop's contact details, or *reload the page* when the
shopper's pass had expired (`neura_core.tenancy.sign_in_message`). Reached by an
agent's own routing (CARE: its order intent with no customer) or by the
ownership gate in ``act`` refusing an order tool to a session with no customer.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph.state import AgentState
from neura_core import get_logger
from neura_core.tenancy import SIGN_IN_WITHOUT_DETAILS

log = get_logger(__name__)

SIGN_IN = "sign_in"

#: What the shopper reads when nothing puts on the shop's details (an eval).
DEFAULT_MESSAGE = SIGN_IN_WITHOUT_DETAILS


async def sign_in(state: AgentState, config: RunnableConfig) -> AgentState:
    """End the turn by asking the shopper to sign in."""
    log.info(
        "sign_in_needed",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
    )
    return {"needs_sign_in": True, "escalated": False, "reply": DEFAULT_MESSAGE}
