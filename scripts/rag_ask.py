#!/usr/bin/env python3
"""Ask the index a question and see what comes back.

    make rag-ask Q="do you sell my personal data?"
    make rag-ask Q="how old do I need to be to order?" K=5

The smoke test proves the pipeline works. This answers the question that comes
up every day afterwards: *why did the agent say that?* — or, more often, why did
it fail to find something you know is in the catalogue.

Reads only. Nothing is indexed, embedded or deleted, so it is safe to run
against whatever is currently in the database.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from neura_agent_core.rag import PostgresVectorStore, Retriever
from neura_commerce import EntityType
from neura_core import Database, configure_logging
from neura_llm import LLMClient

DIM = "\033[2m"
RED = "\033[31m"
OFF = "\033[0m"


async def run(question: str, tenant: str, limit: int, source_type: str | None, show: bool) -> int:
    llm = LLMClient.from_role_map_name("ollama-dev")
    database = Database.from_settings()

    if not await database.ping():
        print(f"{RED}no database — run `make up` and `make migrate`{OFF}")
        return 1

    types = [EntityType(source_type)] if source_type else None

    async with database.tenant_session(tenant) as session:
        retriever = Retriever(PostgresVectorStore(session), llm, tenant_id=tenant)
        result = await retriever.search(question, limit=limit, source_types=types)

    print(f"\n  {question}")
    print(f"  {DIM}namespace {result.namespace} · {len(result)} hit(s){OFF}\n")

    if not result:
        # The whole point of the diagnosis: an empty result must say which of
        # the three possible causes it is.
        print(f"  {RED}nothing found{OFF}")
        print(f"  {DIM}{result.diagnosis}{OFF}\n")
        return 1

    for rank, chunk in enumerate(result.chunks, start=1):
        title = str(chunk.metadata.get("title", "—"))
        print(f"  {rank}. {chunk.score:.3f}  {chunk.source_type.value:<8} {title}")
        if show:
            body = "\n".join(f"       {line}" for line in chunk.content.splitlines()[:8])
            print(f"{DIM}{body}{OFF}")
        print()

    await database.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the index by meaning.")
    parser.add_argument("question", nargs="+", help="what a shopper would type")
    parser.add_argument("--tenant-id", default="tn_ragsmoke")
    parser.add_argument("-k", "--limit", type=int, default=3)
    parser.add_argument(
        "--type", dest="source_type", choices=[t.value for t in EntityType], default=None
    )
    parser.add_argument("--show", action="store_true", help="print the matched text")
    args = parser.parse_args()

    configure_logging(level="ERROR", json_output=False)
    sys.exit(
        asyncio.run(
            run(" ".join(args.question), args.tenant_id, args.limit, args.source_type, args.show)
        )
    )


if __name__ == "__main__":
    main()
