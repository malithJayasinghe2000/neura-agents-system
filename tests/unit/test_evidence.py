"""Captured evidence, and the replay a promoted case runs against — [ADR-0034].

The defect this file guards is subtle and was measured rather than imagined. On
2026-09-06 the first seven promoted cases ran, and **two of the three failures
were the agent being right**: it answered correctly about the July fixture shop
while the assertion had come from the merchant's. A test suite cannot tell those
apart from a regression, which makes every number it reports worthless.

So the assertions below are mostly about *refusals*. A replay that quietly
answered "nothing found" would reproduce the original defect one layer down, and
would look exactly like a passing design.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest

from neura_agent_core.evidence import (
    PII_METHODS,
    RECORDABLE,
    EvidenceBundle,
    EvidenceError,
    RecordingAdapter,
    RecordingRetriever,
    ReplayAdapter,
    ReplayMismatch,
    ReplayRetriever,
    RetrievalEvidence,
    call_key,
    contains_credential,
    derive_inventory,
    export_artefact,
    fingerprint,
    load_artefact,
)
from neura_commerce import Page, ProductQuery
from neura_domain import (
    Category,
    Money,
    Policy,
    PolicyKind,
    Product,
    ProductStatus,
    ProductVariant,
)

#: Pinned, so a capture is byte-identical between two runs of this file and
#: the content-hash assertions below mean what they say.
_SYNCED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _product(
    external_id: str = "1315",
    title: str = "Lightweight Rain Shell",
    *,
    price: str = "110.00",
    quantity: int = 22,
) -> Product:
    return Product(
        tenant_id="tn_capture",
        external_id=external_id,
        neura_id=f"ne_{external_id}",
        platform="fixture",
        synced_at=_SYNCED_AT,
        title=title,
        description="A 2.5-layer waterproof shell rated to 10,000mm with fully taped seams.",
        status=ProductStatus.ACTIVE,
        locale="en",
        category_ids=["32"],
        price_range_min=Money(amount=price, currency="USD"),
        price_range_max=Money(amount=price, currency="USD"),
        variants=[
            ProductVariant(
                external_id=external_id,
                sku=f"NRA-{external_id}",
                title=title,
                price=Money(amount=price, currency="USD"),
                in_stock=quantity > 0,
                stock_quantity=quantity,
            )
        ],
        raw={"platform_only": "this must never be written down"},
    )


class _Store:
    """A store that counts what it was asked. Stands in for a merchant's shop."""

    def __init__(self, products: list[Product] | None = None) -> None:
        self.products = products or [_product()]
        self.calls: list[str] = []

    async def search_products(self, query: ProductQuery) -> Page[Product]:
        self.calls.append(f"search:{query.text}")
        # Deliberately unlike the fixture matcher: this returns everything, the
        # way a real shop answers a two-word query the fake store cannot.
        return Page(items=list(self.products))

    async def get_product(self, external_id: str) -> Product | None:
        self.calls.append(f"get:{external_id}")
        return next((p for p in self.products if p.external_id == external_id), None)

    async def get_policies(self) -> list[Policy]:
        self.calls.append("policies")
        return [
            Policy(
                tenant_id="tn_capture",
                external_id="2",
                neura_id="ne_2",
                platform="fixture",
                synced_at=_SYNCED_AT,
                kind=PolicyKind.RETURNS,
                title="Returns",
                body="Most items may be returned within 30 days of delivery.",
                locale="en",
            )
        ]

    async def list_categories(self) -> list[Category]:
        self.calls.append("categories")
        return [
            Category(
                tenant_id="tn_capture",
                external_id="32",
                neura_id="ne_32",
                platform="fixture",
                synced_at=_SYNCED_AT,
                name="jackets",
                locale="en",
            )
        ]

    async def get_order(self, external_id: str) -> None:
        self.calls.append(f"order:{external_id}")
        return None


async def _capture(store: _Store | None = None) -> tuple[RecordingAdapter, EvidenceBundle]:
    recorder = RecordingAdapter(store or _Store(), store_id="st_one")
    await recorder.search_products(ProductQuery(text="waterproof jacket", limit=5))
    await recorder.get_policies()
    return recorder, recorder.bundle()


class TestCaptureHappensAtTurnTime:
    async def test_the_bundle_holds_what_the_store_returned(self) -> None:
        """ADR-0034 §1. Captured while the turn ran, from the store itself."""
        _, bundle = await _capture()

        assert {call.method for call in bundle.calls} == {"search_products", "get_policies"}
        assert "products" in bundle.entities
        assert bundle.entities["products"][0]["title"] == "Lightweight Rain Shell"

    async def test_recording_does_not_change_what_the_store_answers(self) -> None:
        """A shopper's reply must not depend on whether we captured it."""
        store = _Store()
        recorder = RecordingAdapter(store, store_id="st_one")

        direct = await store.search_products(ProductQuery(text="jacket"))
        recorded = await recorder.search_products(ProductQuery(text="jacket"))

        assert [p.external_id for p in recorded.items] == [p.external_id for p in direct.items]

    async def test_a_failed_call_is_not_recorded(self) -> None:
        """Replaying a transport error would freeze one afternoon's network in."""

        class _Broken(_Store):
            async def get_policies(self) -> list[Policy]:
                raise RuntimeError("the shop had a bad minute")

        recorder = RecordingAdapter(_Broken(), store_id="st_one")
        await recorder.search_products(ProductQuery(text="jacket"))
        with pytest.raises(RuntimeError):
            await recorder.get_policies()

        assert [call.method for call in recorder.bundle().calls] == ["search_products"]

    async def test_nothing_reconstructs_a_bundle_after_the_fact(self) -> None:
        """The whole design, asserted as an absence.

        There is deliberately no function anywhere that builds an
        `EvidenceBundle` from `synced_entities`, because reconstructing history
        from present state is what ADR-0034 rejected — measured, on 2026-09-06,
        as every cited entity having already moved.
        """
        import neura_agent_core.evidence as module

        builders = [
            name
            for name in dir(module)
            if "synced" in name.lower() or "reconstruct" in name.lower()
        ]
        assert builders == []

    async def test_retrieval_is_recorded_onto_the_same_bundle(self) -> None:
        """Both halves of the boundary, or a case replays half a shop."""

        class _Result:
            sources: ClassVar[list[str]] = ["policy:2#0"]

            def __bool__(self) -> bool:
                return True

            def as_context(self) -> str:
                return "Most items may be returned within 30 days."

        class _Retriever:
            async def search(self, query: str, **_: Any) -> _Result:
                return _Result()

        recorder = RecordingAdapter(_Store(), store_id="st_one")
        await RecordingRetriever(_Retriever(), recorder).search("returns policy")

        retrieval = recorder.bundle().retrieval
        assert retrieval is not None
        assert retrieval.query == "returns policy"
        assert "30 days" in retrieval.context

    async def test_a_recording_failure_never_breaks_the_turn(self) -> None:
        """The trade is stated in the code: one unpromotable turn beats one
        failed answer to a shopper."""

        class _Result:
            sources: ClassVar[list[str]] = ["policy:2#0"]

            def __bool__(self) -> bool:
                return True

            def as_context(self) -> str:
                raise RuntimeError("rendering blew up")

        class _Retriever:
            async def search(self, query: str, **_: Any) -> _Result:
                return _Result()

        recorder = RecordingAdapter(_Store(), store_id="st_one")
        result = await RecordingRetriever(_Retriever(), recorder).search("returns")

        assert result is not None
        assert recorder.bundle().retrieval is None


class TestCustomerDataNeverEntersABundle:
    async def test_an_order_lookup_is_forwarded_and_not_recorded(self) -> None:
        """ADR-0034 §8. A promoted case is a file in git."""
        store = _Store()
        recorder = RecordingAdapter(store, store_id="st_one")

        await recorder.get_order("1001")

        assert store.calls == ["order:1001"], "the turn must still work"
        assert recorder.bundle().calls == [], "and nothing about it may be written down"

    async def test_export_refuses_a_turn_whose_tool_declared_pii_output(self) -> None:
        """Generic, and that is the whole fix.

        The refusal used to consult a list of three tool names held in this
        package — agent knowledge in the engine, and a list the *next* agent's
        PII-bearing tool would not be on. It now reads `ToolSpec.pii_output`,
        carried through the bundle, so a new tool is refused with no edit here.
        """
        _, bundle = await _capture()
        bundle = bundle.model_copy(update={"pii_output": True})

        with pytest.raises(EvidenceError, match="customer data"):
            export_artefact(bundle)

    async def test_the_tool_names_do_not_decide_anything(self) -> None:
        """A tool named like an order lookup, declaring no PII output, exports.

        The inverse of the test above, and the reason a name list was wrong:
        names are provenance and the flag is the rule.
        """
        _, bundle = await _capture()
        bundle = bundle.model_copy(update={"tools": ["get_order_status"], "pii_output": False})

        assert export_artefact(bundle)["tools"] == ["get_order_status"]

    async def test_evidence_older_than_the_flag_is_refused(self) -> None:
        """A schema-1 row cannot say whether a PII tool ran, so it is refused
        rather than read optimistically."""
        _, bundle = await _capture()
        stale = bundle.model_copy(update={"schema_version": 1})

        with pytest.raises(EvidenceError, match="predates"):
            export_artefact(stale)

    async def test_export_refuses_a_credential(self) -> None:
        _, bundle = await _capture()
        poisoned = bundle.model_copy(
            update={
                "entities": {
                    "products": [{"external_id": "1", "description": "Bearer sk-abcdefgh12345678"}]
                }
            }
        )

        with pytest.raises(EvidenceError, match="credential"):
            export_artefact(poisoned)

    def test_credential_shapes_are_recognised(self) -> None:
        assert contains_credential({"a": "api_key = 1"}) is not None
        assert contains_credential({"a": "a perfectly ordinary jacket"}) is None


class TestTheExportedArtefact:
    async def test_raw_and_provenance_are_gone_and_the_rest_survives(self) -> None:
        """ADR-0034 §7. `external_id` and `locale` are kept on purpose — the
        first is what every agent reasons with, the second changes what a correct
        answer *is*."""
        _, bundle = await _capture()
        rendered = json.dumps(export_artefact(bundle))

        assert "platform_only" not in rendered, "a platform's own payload reached a file"
        for field in ("neura_id", "synced_at", '"platform"', '"tenant_id"'):
            assert field not in rendered, f"{field} survived export"

        product = export_artefact(bundle)["entities"]["products"][0]
        assert product["external_id"] == "1315"
        assert product["locale"] == "en"

    async def test_the_store_id_is_never_exported(self) -> None:
        _, bundle = await _capture()
        assert bundle.store_id == "st_one"
        assert "st_one" not in json.dumps(export_artefact(bundle))

    async def test_inventory_is_derived_from_the_variants(self) -> None:
        """There is no inventory entity type; stock rides on each variant. A
        fixture without this section silently disables the availability tool."""
        _, bundle = await _capture()

        assert derive_inventory(bundle) == [
            {"variant_external_id": "1315", "quantity": 22, "in_stock": True, "location": None}
        ]

    async def test_an_out_of_stock_variant_derives_as_out_of_stock(self) -> None:
        store = _Store([_product(quantity=0)])
        _, bundle = await _capture(store)

        assert derive_inventory(bundle)[0]["in_stock"] is False

    async def test_a_round_trip_preserves_the_replayable_half(self) -> None:
        _, bundle = await _capture()
        restored = load_artefact(export_artefact(bundle))

        assert [c.key for c in restored.calls] == [c.key for c in bundle.calls]
        assert restored.store_id == "", "an exported artefact cannot name a store"


class TestContentAddressing:
    async def test_the_hash_is_stable_across_identical_captures(self) -> None:
        """ADR-0034 §4. Two turns that saw the same shop share one artefact."""
        _, first = await _capture()
        _, second = await _capture()

        assert first.content_hash() == second.content_hash()

    async def test_the_clock_does_not_change_the_hash(self) -> None:
        _, bundle = await _capture()
        later = bundle.model_copy(update={"captured_at": datetime.now(UTC) + timedelta(days=3)})

        assert later.content_hash() == bundle.content_hash()

    async def test_a_different_shop_is_a_different_artefact(self) -> None:
        _, cheap = await _capture(_Store([_product(price="110.00")]))
        _, dear = await _capture(_Store([_product(price="165.00")]))

        assert cheap.content_hash() != dear.content_hash()

    def test_a_fingerprint_moves_only_when_content_moves(self) -> None:
        document = {"external_id": "1", "title": "Rain Shell", "price": "110.00"}

        assert fingerprint(document) == fingerprint(dict(reversed(list(document.items()))))
        assert fingerprint(document) != fingerprint({**document, "price": "165.00"})

    def test_provenance_does_not_affect_a_fingerprint(self) -> None:
        """Otherwise every entity would look changed after any sync."""
        content = {"external_id": "1", "title": "Rain Shell"}

        assert fingerprint(content) == fingerprint(
            {**content, "neura_id": "ne_9", "synced_at": "2026-09-05", "raw": {"x": 1}}
        )


class TestReplayIsDeterministic:
    async def test_a_recorded_search_replays_exactly(self) -> None:
        _, bundle = await _capture()
        replay = ReplayAdapter(bundle)

        page = await replay.search_products(ProductQuery(text="waterproof jacket", limit=5))

        assert [p.title for p in page.items] == ["Lightweight Rain Shell"]
        assert str(page.items[0].price_range_min.amount) == "110.00"

    async def test_the_two_word_query_the_fixture_matcher_cannot_answer(self) -> None:
        """The measured case, and the reason replay exists at all.

        `waterproof jacket` returns 0 from the fixture store's matcher, which
        requires every term to match, and returned three products from the shop
        the grade came from. Replay answers what the shop answered — **without
        the matcher being changed**, which ADR-0034 rejected explicitly.
        """
        _, bundle = await _capture()

        page = await ReplayAdapter(bundle).search_products(
            ProductQuery(text="waterproof jacket", limit=5)
        )

        assert len(page.items) == 1, "replay must answer as the merchant's store did"

    async def test_replay_is_the_same_every_time(self) -> None:
        _, bundle = await _capture()
        replay = ReplayAdapter(bundle)
        query = ProductQuery(text="waterproof jacket", limit=5)

        first = await replay.search_products(query)
        second = await replay.search_products(query)

        assert [p.model_dump() for p in first.items] == [p.model_dump() for p in second.items]

    async def test_retrieval_replays_in_the_shape_the_node_reads(self) -> None:
        """The assertion this test used to make was `result.context == "30 days"`,
        which is true of the stored model and says nothing about whether the
        graph can use it. The first real promoted case then crashed with
        `'RetrievalEvidence' object has no attribute 'as_context'`.

        So it now asserts the **interface `retrieve` actually calls**, member by
        member. A test shaped like the storage rather than like the caller is a
        test that passes while the thing it guards is broken.
        """
        bundle = EvidenceBundle(
            store_id="st_one",
            retrieval=RetrievalEvidence(
                query="returns", context="30 days", sources=["policy:2#0"], top_score=0.81
            ),
        )

        result = await ReplayRetriever(bundle).search("returns")

        assert result.as_context() == "30 days"
        assert result.sources == ["policy:2#0"]
        assert result.diagnosis is None
        assert result.top_score == 0.81
        assert bool(result) is True
        assert len(result) == 1

    async def test_every_member_retrieve_uses_is_present(self) -> None:
        """Pinned against the node's source, so the two cannot drift apart.

        `retrieve.py` is the only consumer; if it starts reading a sixth member,
        this fails here rather than in a promoted case months later.
        """
        import inspect

        from neura_agent_core.graph.nodes import retrieve as node

        source = inspect.getsource(node)
        used = {
            m
            for m in ("as_context", "sources", "diagnosis", "top_score")
            if f"result.{m}" in source
        }

        result = await ReplayRetriever(
            EvidenceBundle(store_id="st_one", retrieval=RetrievalEvidence(query="q", context="c"))
        ).search("q")

        assert used, "the node stopped reading the result at all — check this test"
        for member in used:
            assert hasattr(result, member), f"replay cannot satisfy result.{member}"

    async def test_an_empty_recorded_retrieval_replays_as_falsy(self) -> None:
        """A turn whose retrieval genuinely found nothing must replay as nothing
        found — not as a truthy empty object the node treats as a hit."""
        bundle = EvidenceBundle(
            store_id="st_one",
            retrieval=RetrievalEvidence(query="q", context="", diagnosis="namespace empty"),
        )

        result = await ReplayRetriever(bundle).search("q")

        assert bool(result) is False
        assert result.diagnosis == "namespace empty"

    async def test_capabilities_come_from_the_bundle(self) -> None:
        """A store that could not search must not replay as one that could."""
        from neura_domain import Capability

        bundle = EvidenceBundle(store_id="st_one", capabilities=[Capability.PRODUCT_READ.value])

        assert ReplayAdapter(bundle).capabilities == frozenset({Capability.PRODUCT_READ})

    def test_an_unknown_capability_is_dropped_rather_than_crashing(self) -> None:
        bundle = EvidenceBundle(store_id="st_one", capabilities=["product.read", "invented.thing"])

        assert ReplayAdapter(bundle).capabilities  # the real one survives


class TestAMismatchFailsLoudly:
    """ADR-0034 §6 — the most important behaviour in the module.

    An empty result would be indistinguishable from a shop that stocks nothing,
    which is the *original* defect reappearing one layer down: `no_match` would
    be reached honestly, the agent would say "we could not find any", and the
    case would fail for a reason nobody could see.
    """

    async def test_an_unrecorded_query_raises(self) -> None:
        _, bundle = await _capture()

        with pytest.raises(ReplayMismatch) as caught:
            await ReplayAdapter(bundle).search_products(ProductQuery(text="fishing rods"))

        assert "fishing rods" in str(caught.value)

    async def test_the_diagnostic_names_what_was_recorded(self) -> None:
        """Otherwise a reader cannot tell a reworded query from a regression."""
        _, bundle = await _capture()

        with pytest.raises(ReplayMismatch) as caught:
            await ReplayAdapter(bundle).get_product("9999")

        message = str(caught.value)
        assert "search_products" in message and "get_policies" in message

    async def test_it_never_returns_an_empty_page(self) -> None:
        _, bundle = await _capture()
        replay = ReplayAdapter(bundle)

        for call in (
            replay.search_products(ProductQuery(text="nothing like this")),
            replay.list_categories(),
            replay.get_inventory(["v_unknown"]),
        ):
            with pytest.raises(ReplayMismatch):
                await call

    async def test_an_order_can_never_be_replayed(self) -> None:
        _, bundle = await _capture()

        with pytest.raises(ReplayMismatch, match="never recorded"):
            await ReplayAdapter(bundle).get_order("1001")

    async def test_retrieval_with_no_recording_raises(self) -> None:
        with pytest.raises(ReplayMismatch, match="recorded none"):
            await ReplayRetriever(EvidenceBundle(store_id="st_one")).search("anything")

    def test_a_call_key_distinguishes_arguments(self) -> None:
        assert call_key("search_products", {"query": {"text": "a"}}) != call_key(
            "search_products", {"query": {"text": "b"}}
        )

    def test_a_call_key_ignores_key_order(self) -> None:
        assert call_key("m", {"a": 1, "b": 2}) == call_key("m", {"b": 2, "a": 1})


class TestAnEmptyBundle:
    def test_is_recognised(self) -> None:
        assert EvidenceBundle(store_id="st_one").is_empty

    async def test_a_captured_turn_is_not(self) -> None:
        _, bundle = await _capture()
        assert not bundle.is_empty

    def test_retrieval_alone_is_enough(self) -> None:
        bundle = EvidenceBundle(
            store_id="st_one",
            retrieval=RetrievalEvidence(query="returns", context="30 days"),
        )
        assert not bundle.is_empty


class TestTheRecordedSurfaceIsPinned:
    """`RECORDABLE` and `PII_METHODS` claim to be pinned by a test. This is it.

    Without them these are two constants nobody consults — and the comment above
    `RECORDABLE` would be describing a check that does not exist, which is the
    failure this log records under [Finding 26](../../docs/TESTING_LOG.md) and
    twice before it.
    """

    def test_the_recorder_records_exactly_the_allowlist(self) -> None:
        """A method added to the adapter protocol must be a deliberate decision.

        The default for anything new is **not recorded**, because the wrong
        direction of this mistake writes a merchant's customer data into a file
        that goes to git.
        """
        recorder = RecordingAdapter(_Store(), store_id="st_one")
        recorded = {
            name
            for name in dir(RecordingAdapter)
            if not name.startswith("_") and callable(getattr(recorder, name, None))
        } - {"bundle", "note_tools", "note_retrieval"}

        assert recorded == RECORDABLE | PII_METHODS

    def test_every_pii_method_is_forwarded_and_none_is_recorded(self) -> None:
        """The two sets do not overlap, and the second is never written down."""
        assert not (RECORDABLE & PII_METHODS)

    async def test_every_pii_method_refuses_to_replay(self) -> None:
        _, bundle = await _capture()
        replay = ReplayAdapter(bundle)

        for method in sorted(PII_METHODS):
            with pytest.raises(ReplayMismatch):
                await _call(getattr(replay, method))

    async def test_every_pii_method_writes_nothing_to_a_bundle(self) -> None:
        recorder = RecordingAdapter(_Store(), store_id="st_one")

        for method in sorted(PII_METHODS):
            with contextlib.suppress(AttributeError, TypeError):
                await _call(getattr(recorder, method))

        assert recorder.bundle().calls == []


async def _call(method: Any) -> Any:
    """Call an adapter method with whatever shape its first argument takes."""
    import inspect

    parameters = [
        p
        for name, p in inspect.signature(method).parameters.items()
        if p.default is inspect.Parameter.empty
    ]
    if not parameters:
        return await method()
    name = parameters[0].name
    return await method([] if name.endswith("ids") else "1001")
