"""One populated merchant, built the way the product builds one.

Every console integration test needs the same thing: a person, a shop they hold
a membership for, and enough real rows behind it that a screen has something to
render. Written once here because `console.md §6.4` requires **two populated
tenants** in every isolation assertion — and a fixture duplicated per test file
is a fixture that drifts, which for an isolation test means the second tenant
quietly stops being populated and the assertion stops asserting anything.

**Built through the repositories the serving path uses**, not by hand-writing
rows. A fixture that invents its own shape tests the fixture: `append_turn`
writes two messages and bumps the conversation's counters, `ShadowRepository`
mints the id, `UsageMeter` upserts by day and agent. Any of those changing should
break these tests, which is the point of them.

Cleanup is **by id**, never by tenant. These run against a developer's own
database where the ids are real, and a teardown that deleted "this tenant's
conversations" would be a data-loss bug living inside a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete

from neura_agent_core.conversations import (
    ConversationRepository,
    ConversationState,
    conversation_messages,
    conversations,
)
from neura_agent_core.rag.schema import document_chunks
from neura_agent_core.shadow import ShadowRepository, ShadowTurn, shadow_turns
from neura_commerce.sync.schema import sync_checkpoints
from neura_core import Database, ids
from neura_core.identity.schema import login_tokens, memberships, users
from neura_core.tenancy.schema import tenant_stores, tenant_usage
from neura_core.tenancy.usage import UsageDelta, UsageMeter

#: The shopper's question, on every seeded conversation. Distinctive enough that
#: finding it on a rendered page cannot be a coincidence.
QUESTION = "can I return these boots after 20 days?"

#: The reply the shopper actually received, on the answered conversation.
REPLY = "Yes — unworn boots can be returned within 30 days of delivery."

#: The merchant's own words, indexed and cited. What "show the evidence" means.
POLICY = "Returns are accepted within 30 days of delivery, unworn."

#: A tokenised message, so a screen's handling of `[EMAIL_1]` is exercised
#: against a real row rather than against a regex somebody trusted.
TOKENISED_QUESTION = "my address is [ADDRESS_1] and my email is [EMAIL_1] — where is my order?"

#: The platform a seeded store claims. A *value in a column*, never a branch in
#: code — `AGENTS.md` rule 1 is about platform names appearing in logic, and a
#: fixture that named a real one here would still put the string in a file
#: outside `neura-adapters`. So it is deliberately not a real platform.
PLATFORM = "console-fixture"


@dataclass
class Shop:
    """Everything one seeded merchant is made of, so teardown can find it again."""

    user: str
    email: str
    tenant: str
    membership: str
    #: The conversation the shopper got an answer in.
    answered_conversation: str = ""
    #: The conversation held in shadow mode — the shopper saw nothing.
    shadowed_conversation: str = ""
    #: The conversation the agent handed to a person.
    escalated_conversation: str = ""
    chunk: str = ""
    store: str = ""
    #: Shadow turn ids: one with a draft and evidence, one the agent declined.
    answered_turn: str = ""
    declined_turn: str = ""
    message_ids: list[str] = field(default_factory=list)


async def make_shop(db: Database) -> Shop:
    """A merchant with an owner, three conversations, two shadow turns, an
    indexed policy, a connected store and a day of usage."""
    user = ids.new_id(ids.USER)
    shop = Shop(
        user=user,
        email=f"{user}@example.com",
        tenant=ids.new_id(ids.TENANT),
        membership=ids.new_id(ids.MEMBERSHIP),
    )

    async with db.identity_session() as session:
        await session.execute(users.insert().values(id=shop.user, email=shop.email, name="Owner"))

    async with db.tenant_session(shop.tenant) as session:
        await session.execute(
            memberships.insert().values(
                id=shop.membership,
                tenant_id=shop.tenant,
                user_id=shop.user,
                role="owner",
            )
        )

        await _conversations(session, shop)
        await _evidence(session, shop)
        await _shadow_turns(session, shop)
        await _store(session, shop)
        await UsageMeter(session).record(
            shop.tenant,
            "care",
            UsageDelta(
                conversations=3,
                turns=4,
                llm_calls=9,
                tool_calls=2,
                escalations=1,
                blocked=0,
                prompt_tokens=4210,
                completion_tokens=880,
                # Zero on purpose. It is what a local model records *and* what an
                # unpriced cloud model records, and every screen that shows money
                # has to tell a merchant which — `CLAUDE.md §4`.
                cost_usd=Decimal("0"),
            ),
        )

    return shop


async def drop_shop(db: Database, shop: Shop) -> None:
    """Remove exactly what `make_shop` created."""
    made_conversations = [
        c
        for c in (
            shop.answered_conversation,
            shop.shadowed_conversation,
            shop.escalated_conversation,
        )
        if c
    ]

    async with db.tenant_session(shop.tenant) as session:
        await session.execute(
            delete(shadow_turns).where(
                shadow_turns.c.id.in_([shop.answered_turn, shop.declined_turn])
            )
        )
        await session.execute(delete(document_chunks).where(document_chunks.c.id == shop.chunk))
        await session.execute(
            delete(conversation_messages).where(
                conversation_messages.c.conversation_id.in_(made_conversations)
            )
        )
        await session.execute(
            delete(conversations).where(conversations.c.id.in_(made_conversations))
        )
        await session.execute(delete(tenant_stores).where(tenant_stores.c.id == shop.store))
        await session.execute(
            delete(sync_checkpoints).where(sync_checkpoints.c.tenant_id == shop.tenant)
        )
        await session.execute(delete(tenant_usage).where(tenant_usage.c.tenant_id == shop.tenant))
        await session.execute(delete(memberships).where(memberships.c.id == shop.membership))

    async with db.identity_session() as session:
        await session.execute(delete(login_tokens).where(login_tokens.c.user_id == shop.user))
        await session.execute(delete(users).where(users.c.id == shop.user))


async def _conversations(session, shop: Shop) -> None:
    """Three threads, and the three are not interchangeable.

    One **answered** (the shopper read a reply), one **escalated** (a person now
    has to deal with it), one **shadowed** (the shopper was shown nothing and the
    draft went to Review). A fixture with three answered conversations would let
    a screen that collapsed all five states into "done" pass every test.
    """
    repository = ConversationRepository(session)

    shop.answered_conversation = ids.new_id(ids.CONVERSATION)
    await repository.start(
        shop.tenant, conversation_id=shop.answered_conversation, agent_key="care"
    )
    _, message_id = await repository.append_turn(
        shop.tenant,
        shop.answered_conversation,
        shopper=QUESTION,
        reply=REPLY,
        state=ConversationState.RESOLVED,
        intent="policy_question",
        citations=[{"type": "policy", "id": "fixture-returns"}],
    )
    shop.message_ids.append(message_id)

    shop.escalated_conversation = ids.new_id(ids.CONVERSATION)
    await repository.start(
        shop.tenant, conversation_id=shop.escalated_conversation, agent_key="care"
    )
    # Tokenised, exactly as the guard leaves it. The screens must explain
    # `[EMAIL_1]` rather than render it as though the data were lost.
    await repository.append_turn(
        shop.tenant,
        shop.escalated_conversation,
        shopper=TOKENISED_QUESTION,
        reply="Let me put you through to someone who can look that up.",
        state=ConversationState.ESCALATED,
        intent="order_status",
    )

    shop.shadowed_conversation = ids.new_id(ids.CONVERSATION)
    await repository.start(
        shop.tenant, conversation_id=shop.shadowed_conversation, agent_key="care"
    )
    # A shadowed turn writes the shopper's message and **no reply** — the reply
    # was never said, so it is not history (shadow.py).
    shop.message_ids.append(
        await repository.append_shopper_message(
            shop.tenant, shop.shadowed_conversation, shopper=QUESTION
        )
    )


async def _evidence(session, shop: Shop) -> None:
    shop.chunk = ids.new_id(ids.CHUNK)
    await session.execute(
        document_chunks.insert().values(
            id=shop.chunk,
            tenant_id=shop.tenant,
            embedding_model="console-fixture",
            dimensions=3,
            # pgvector's text form, as `rag/postgres._to_vector` writes it. The
            # value is irrelevant: nothing here searches.
            embedding="[0,0,0]",
            content=POLICY,
            content_hash="console-fixture",
            source_type="policy",
            source_id="fixture-returns",
            chunk_index=0,
        )
    )


async def _shadow_turns(session, shop: Shop) -> None:
    repository = ShadowRepository(session)

    shop.answered_turn = await repository.record(
        ShadowTurn(
            tenant_id=shop.tenant,
            conversation_id=shop.shadowed_conversation,
            message_id=shop.message_ids[-1],
            agent_key="care",
            mode="shadow",
            state="resolved",
            intent="policy_question",
            draft=REPLY,
            grounded=True,
            citations=[
                {"type": "policy", "id": "fixture-returns"},
                {"type": "tool", "id": "get_order"},
            ],
            tools=["get_order"],
            cost_usd=Decimal("0"),
            latency_ms=1180,
        )
    )
    # The interesting one, and the row a lazy queue omits: the agent declined.
    shop.declined_turn = await repository.record(
        ShadowTurn(
            tenant_id=shop.tenant,
            conversation_id=shop.shadowed_conversation,
            message_id=shop.message_ids[-1],
            agent_key="care",
            mode="shadow",
            state="escalated",
            draft="",
            escalated=True,
            grounded=False,
            verify_reason="the draft claimed a refund window the policy does not state",
        )
    )


async def _store(session, shop: Shop) -> None:
    """A connected shop, and a sync that has run once.

    ``credentials`` and ``wrapped_dek`` hold obvious placeholders rather than a
    real envelope: **no console endpoint may return either field**, so a test
    that asserts their absence needs them present and recognisable, not valid.
    """
    shop.store = ids.new_id(ids.STORE)
    await session.execute(
        tenant_stores.insert().values(
            id=shop.store,
            tenant_id=shop.tenant,
            platform=PLATFORM,
            base_url="https://shop.example.com/neura/v1",
            credentials="FIXTURE-CIPHERTEXT-MUST-NEVER-BE-RETURNED",
            wrapped_dek="FIXTURE-WRAPPED-DEK-MUST-NEVER-BE-RETURNED",
            status="active",
        )
    )
    await session.execute(
        sync_checkpoints.insert().values(
            tenant_id=shop.tenant,
            platform=PLATFORM,
            entity_type="product",
            cursor="fixture-cursor",
            updated_through=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            last_run_count=42,
        )
    )


__all__ = [
    "PLATFORM",
    "POLICY",
    "QUESTION",
    "REPLY",
    "TOKENISED_QUESTION",
    "Shop",
    "drop_shop",
    "make_shop",
]
