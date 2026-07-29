"""The ``retrieve`` node — semantic search, wrapped for a prompt.

Thin on purpose. Milestone 1.9 built the retrieval layer and proved it against a
real catalogue; this node's whole job is to call it with the conversation's
tenant, and to hand the result on in a form the composer can safely use.

**Two properties it must not lose:**

* Retrieved text is **untrusted**. A merchant's product description is
  user-generated content and a real indirect-injection vector — "ignore previous
  instructions" in a product blurb is a live attack (security-model.md §2.3).
  ``as_context()`` wraps every chunk in an explicit delimiter. That is not a
  defence by itself; it is what makes the guard node's job and a human
  reviewer's job possible.
* **Retrieval failure is not turn failure.** A shopper asking "where is my
  order?" needs a tool, not the catalogue. If retrieval finds nothing, or the
  vector store is unreachable, the turn continues with no context and says so —
  ``agent-runtime.md §2`` specifies exactly that: *"failure → continue with no
  context"*.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph.state import AgentState, runtime_of
from neura_agent_core.rag.retrieval import DEFAULT_LIMIT
from neura_core import get_logger

log = get_logger(__name__)


async def retrieve(state: AgentState, config: RunnableConfig) -> AgentState:
    """Search the tenant's indexed catalogue and policies for this message."""
    runtime = runtime_of(config or {})

    if runtime.retriever is None:
        # A legitimate configuration, not an error: an agent that answers purely
        # from tools needs no index. Recorded so it is never mistaken for an
        # index that came back empty.
        return {"context": "", "sources": [], "retrieval_note": "retrieval not configured"}

    query = state.get("message", "")

    try:
        result = await runtime.retriever.search(query, limit=DEFAULT_LIMIT)
    except Exception as exc:
        # The graph continues. An answerable-from-tools question must not fail
        # because pgvector had a bad moment.
        log.warning(
            "retrieve_failed",
            conversation_id=state.get("conversation_id"),
            error=str(exc),
        )
        return {
            "context": "",
            "sources": [],
            "retrieval_note": f"retrieval unavailable: {type(exc).__name__}",
        }

    update: AgentState = {
        "context": result.as_context(),
        "sources": result.sources,
    }
    if result.diagnosis:
        # Carried into the trace. A namespace mismatch reads as "the agent got
        # dumber" unless something says otherwise, and this is that something
        # (llm-abstraction.md §5).
        update["retrieval_note"] = result.diagnosis

    log.info(
        "retrieve_done",
        conversation_id=state.get("conversation_id"),
        hits=len(result),
        top_score=round(result.top_score, 4),
    )
    return update
