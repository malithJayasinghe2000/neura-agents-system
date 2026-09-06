"""A promoted case, from its refusals to the store it actually runs against.

Companion to `test_evidence.py`, which covers capture and replay in isolation.
This file is about the *seam*: that an invented case still gets exactly the store
it always got, that a promoted one gets the boundary its turn recorded and
**not** the base fixture, and that promotion refuses everything [ADR-0034] §8
says it must.

The failure being guarded is the one measured on 2026-09-06: a case can fail
while the agent is right, and nothing in a report distinguishes that from a
regression.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from neura_evals.dataset import EvalCase, FixtureMode, load_all

from neura_agent_core.evidence import (
    EvidenceBundle,
    EvidenceError,
    RecordedCall,
    ReplayAdapter,
    RetrievalEvidence,
    _dump,
    artefact_path,
    call_key,
    export_artefact,
    load_artefact,
    read_artefact,
)
from neura_agent_core.review import TOOL_NOT_RECORDED
from neura_commerce import ProductQuery

REPO = Path(__file__).resolve().parents[2]

CARE_FIXTURES = REPO / "agents/care/src/neura_agent_care/evals/fixtures"
SELL_FIXTURES = REPO / "agents/sell/src/neura_agent_sell/evals/fixtures"


def _promote_module() -> Any:
    """`scripts/promote_turn.py`, loaded by path.

    It is a script rather than a package on purpose — ADR-0032 §9 puts promotion
    in the hands of somebody holding the repository — so there is nothing to
    import by name.
    """
    spec = importlib.util.spec_from_file_location("promote_turn", REPO / "scripts/promote_turn.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The exact query a captured turn made. Built through the same `_dump` the
#: recorder uses rather than typed out, because a hand-written argument dict
#: hashes to a different key and the test would then be asserting against a
#: call nothing ever recorded.
QUERY = ProductQuery(text="waterproof jacket", limit=5)


def _bundle(**overrides: Any) -> EvidenceBundle:
    arguments = {"query": _dump(QUERY)}
    defaults: dict[str, Any] = {
        "store_id": "st_one",
        "captured_at": datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        "calls": [
            RecordedCall(
                method="search_products",
                key=call_key("search_products", arguments),
                arguments=arguments,
                result={"items": [], "next_cursor": None},
            )
        ],
        "tools": ["search_products"],
        "entities": {
            "products": [
                {
                    "external_id": "1315",
                    "title": "Lightweight Rain Shell",
                    "locale": "en",
                    "variants": [{"external_id": "1315", "in_stock": True, "stock_quantity": 22}],
                }
            ]
        },
        "source_fingerprints": {"products:1315": "abc123"},
    }
    return EvidenceBundle(**{**defaults, **overrides})


class TestFixtureModeIsExplicit:
    """[ADR-0034] §5. Never inferred from a filename or from `synthetic`."""

    def test_a_case_that_says_nothing_overlays(self) -> None:
        case = EvalCase(id="c1", intent="policy_qa", input="hi", expect={}, synthetic=True)

        assert case.fixture_mode is FixtureMode.OVERLAY

    def test_replay_without_evidence_is_refused(self) -> None:
        """Otherwise it falls through to an empty store and fails as though the
        shop stocked nothing — §6's failure, before replay can raise."""
        with pytest.raises(ValueError, match="names no evidence"):
            EvalCase(
                id="c1",
                intent="policy_qa",
                input="hi",
                expect={},
                fixture_mode=FixtureMode.REPLAY,
            )

    def test_evidence_without_replay_is_refused(self) -> None:
        """A half-converted case, whose unconverted half decides what it runs
        against."""
        with pytest.raises(ValueError, match="would be ignored"):
            EvalCase(id="c1", intent="policy_qa", input="hi", expect={}, evidence="abc")


class TestInventedCasesAreUntouched:
    def test_every_shipped_case_still_overlays(self) -> None:
        """The regression that would matter most, and would be silent.

        ADR-0034 changes how *promoted* cases get their store. If it changed how
        the invented ones do, every existing number in this project would move
        for a reason nobody had asked about.
        """
        for dataset in _shipped():
            for case in dataset.cases:
                if dataset.name != "graded":
                    assert case.fixture_mode is FixtureMode.OVERLAY, (
                        f"{case.id} is not an overlay case and it should be"
                    )

    def test_the_base_fixture_still_answers_an_invented_case(self) -> None:
        from neura_agent_care.evals.store import load_store

        store = load_store("tn_eval_care", [])

        assert store is not None

    async def test_the_fixture_matcher_is_unchanged(self) -> None:
        """ADR-0034 rejected loosening it, explicitly.

        `waterproof jacket` returning 0 against a catalogue holding a waterproof
        shell and a field jacket is *correct behaviour for a fixture store* — it
        requires every term to match. Replay is how a promoted case gets the
        merchant's answer instead; imitating a search engine no merchant has is
        not.
        """
        from neura_agent_care.evals.store import load_store

        store = load_store("tn_eval_care", [])
        page = await store.search_products(ProductQuery(text="waterproof jacket"))

        assert len(page.items) == 0


class TestPromotedCasesDoNotSeeTheBaseFixture:
    async def test_replay_answers_only_what_was_recorded(self) -> None:
        """The base fixture's Waterproof Hiking Shoe must not be reachable.

        Measured on 2026-09-06: overlaying a merchant's catalogue onto the base
        produced two different products both called "Waterproof Hiking Shoe", at
        119.00 GBP and 132.00 USD. A case asserting a price against that shop is
        asserting it against a coin toss.
        """
        replay = ReplayAdapter(_bundle())

        recorded = await replay.search_products(QUERY)
        assert recorded.items == []

        from neura_agent_core.evidence import ReplayMismatch

        with pytest.raises(ReplayMismatch):
            # The base fixture holds this. Replay must not.
            await replay.get_product("p_100")

    def test_the_replay_store_is_not_a_fixture_store(self) -> None:
        """Nothing about it can load `store.json`, by construction."""
        replay = ReplayAdapter(_bundle())

        assert not hasattr(replay, "_products")
        assert not hasattr(replay, "load_store")


class TestPromotionRefusals:
    """[ADR-0034] §8. Every one of these is a rule enforced rather than described."""

    def test_missing_evidence_refuses(self) -> None:
        problems = _promote_module().evidence_problems(None)

        assert len(problems) == 1
        assert "no evidence was captured" in problems[0]

    def test_the_refusal_says_reconstruction_is_not_offered(self) -> None:
        """A reader who does not know that will go looking for the flag."""
        assert "synced" in _promote_module().evidence_problems(None)[0]

    def test_empty_evidence_refuses(self) -> None:
        problems = _promote_module().evidence_problems(EvidenceBundle(store_id="st_one"))

        assert any("no successful store call" in p for p in problems)

    def test_a_tool_declaring_pii_output_refuses(self) -> None:
        bundle = _bundle(pii_output=True)

        problems = _promote_module().evidence_problems(bundle)

        assert any("customer data" in p for p in problems)

    def test_evidence_predating_the_flag_refuses(self) -> None:
        """Schema 1 has no `pii_output`, so "no PII" is unknowable, not false."""
        problems = _promote_module().evidence_problems(_bundle(schema_version=1))

        assert any("predates" in p for p in problems)

    def test_a_credential_refuses(self) -> None:
        bundle = _bundle(entities={"products": [{"external_id": "1", "title": "api_key: hunter2"}]})

        problems = _promote_module().evidence_problems(bundle)

        assert any("credential" in p for p in problems)

    def test_a_good_bundle_passes(self) -> None:
        assert _promote_module().evidence_problems(_bundle()) == []

    def test_retrieval_alone_is_enough_to_promote(self) -> None:
        bundle = EvidenceBundle(
            store_id="st_one",
            retrieval=RetrievalEvidence(query="returns", context="30 days"),
        )

        assert _promote_module().evidence_problems(bundle) == []


class TestAPromotedCaseAssertsWhatItKnows:
    def test_a_turn_that_used_no_tools_asserts_the_empty_list(self) -> None:
        """`[]` is a fact the turn establishes, not a gap in the case.

        Leaving it out left the first real promoted case unscored for tool
        selection — and an unscored assertion is the `tool_selection_accuracy`
        vacuum of 2026-08-27 arriving one case at a time.
        """
        module = _promote_module()
        turn = SimpleNamespace(
            intent="policy_qa",
            escalated=False,
            grounded=True,
            tools=[],
            verdict=None,
            draft="d",
            id="msg_1",
            agent_key="care",
            reviewed_by="usr_1",
            created_at=datetime(2026, 9, 6, tzinfo=UTC),
            note="",
        )

        case = module.build_case(turn, "q", [], case_id="c", evidence_hash="h")

        assert case["expect"]["tools_called"] == []

    def test_a_turn_that_used_tools_names_them(self) -> None:
        module = _promote_module()
        turn = SimpleNamespace(
            intent="product_qa",
            escalated=False,
            grounded=True,
            tools=["search_products", "check_stock"],
            verdict=None,
            draft="d",
            id="msg_1",
            agent_key="care",
            reviewed_by="usr_1",
            created_at=datetime(2026, 9, 6, tzinfo=UTC),
            note="",
        )

        case = module.build_case(turn, "q", [], case_id="c", evidence_hash="h")

        assert case["expect"]["tools_called"] == ["check_stock", "search_products"]


class TestCaseIdsAreCollisionSafe:
    def test_a_deleted_case_does_not_cause_a_collision(self) -> None:
        """ADR-0032 §9 makes deletion the only way to remove a case, so a gap in
        the numbering is the ordinary state rather than the exotic one. Counting
        the cases would reuse an id the moment one was deleted."""
        module = _promote_module()
        cases = [{"id": "graded_care_001"}, {"id": "graded_care_003"}]

        assert module.next_case_id("care", cases) == "graded_care_002"

    def test_an_empty_dataset_starts_at_one(self) -> None:
        assert _promote_module().next_case_id("care", []) == "graded_care_001"


class TestArtefactsAreImmutable:
    def test_an_existing_artefact_is_not_rewritten(self, tmp_path: Path) -> None:
        """Content-addressed, so a file with this name already holds these bytes.

        Rewriting it is a write that can only ever do harm — and if the bytes
        somehow differed, overwriting would silently change what an
        already-promoted case replays.
        """
        module = _promote_module()
        bundle = _bundle()
        content_hash = export_artefact(bundle)["_content_hash"]

        module.AGENT_FIXTURES["care"] = tmp_path
        path = artefact_path(tmp_path, content_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"deliberately": "not the export"}')

        assert module.write_artefact("care", bundle) == content_hash
        assert json.loads(path.read_text()) == {"deliberately": "not the export"}

    def test_the_write_is_atomic(self, tmp_path: Path) -> None:
        """No temporary file survives a successful write."""
        module = _promote_module()
        module.AGENT_FIXTURES["care"] = tmp_path

        module.write_artefact("care", _bundle())

        assert list(tmp_path.glob("**/*.tmp")) == []

    def test_the_filename_is_the_content_hash(self, tmp_path: Path) -> None:
        module = _promote_module()
        module.AGENT_FIXTURES["care"] = tmp_path

        content_hash = module.write_artefact("care", _bundle())

        assert artefact_path(tmp_path, content_hash).exists()


class TestBothAgentsCanReplay:
    """One implementation, two agents, neither importing the other."""

    @pytest.mark.parametrize("agent", ["care", "sell"])
    def test_the_target_chooses_a_store_by_mode(self, agent: str, tmp_path: Path) -> None:
        module = __import__(f"neura_agent_{agent}.evals.target", fromlist=["_store_for"])
        case = EvalCase(
            id=f"graded_{agent}_001",
            intent="policy_qa" if agent == "care" else "recommend",
            input="anything",
            expect={},
            synthetic=True,
        )

        store, capabilities, retriever = module._store_for(case, f"tn_eval_{agent}")

        assert capabilities, "an overlay case keeps the full fixture capability set"
        assert retriever is None, "an invented case has no retriever, as before"
        assert not isinstance(store, ReplayAdapter)

    @pytest.mark.parametrize(
        ("agent", "fixtures"), [("care", CARE_FIXTURES), ("sell", SELL_FIXTURES)]
    )
    def test_a_replay_case_reaches_the_replay_adapter(
        self, agent: str, fixtures: Path, tmp_path: Path
    ) -> None:
        module = __import__(f"neura_agent_{agent}.evals.target", fromlist=["_store_for"])
        bundle = _bundle()
        payload = export_artefact(bundle)
        content_hash = str(payload["_content_hash"])

        path = artefact_path(fixtures, content_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        try:
            case = EvalCase(
                id=f"graded_{agent}_001",
                intent="policy_qa" if agent == "care" else "recommend",
                input="anything",
                expect={},
                fixture_mode=FixtureMode.REPLAY,
                evidence=content_hash,
            )

            store, _, retriever = module._store_for(case, f"tn_eval_{agent}")

            assert isinstance(store, ReplayAdapter)
            assert retriever is None, "this bundle recorded no retrieval"
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.parametrize("agent", ["care", "sell"])
    def test_missing_evidence_names_the_path_rather_than_answering_empty(self, agent: str) -> None:
        from neura_agent_core.evidence import EvidenceError

        module = __import__(f"neura_agent_{agent}.evals.target", fromlist=["_store_for"])
        case = EvalCase(
            id=f"graded_{agent}_001",
            intent="policy_qa" if agent == "care" else "recommend",
            input="anything",
            expect={},
            fixture_mode=FixtureMode.REPLAY,
            evidence="0" * 64,
        )

        with pytest.raises(EvidenceError, match="no evidence artefact"):
            module._store_for(case, f"tn_eval_{agent}")


class TestTheMerchantFacingText:
    def test_it_no_longer_claims_the_audit_log_holds_the_result(self) -> None:
        """[ADR-0034] §10. `audit_log` has only ever held `guard.block` rows, so
        the old sentence promised a merchant a record that did not exist —
        [Finding 20](../../docs/TESTING_LOG.md)'s shape, on the same screen."""
        assert "audit log" not in TOOL_NOT_RECORDED.lower()

    def test_it_still_says_something_true_and_useful(self) -> None:
        """Deleting the false half must not leave an empty panel, which is the
        one outcome indistinguishable from a bug (ADR-0020's argument)."""
        assert "This lookup ran." in TOOL_NOT_RECORDED
        assert "not kept in this queue" in TOOL_NOT_RECORDED

    def test_no_module_still_promises_an_audit_trail_of_tool_results(self) -> None:
        """The docstring repeated the same claim and was corrected with it."""
        source = (REPO / "packages/neura-agent-core/src/neura_agent_core/review.py").read_text()
        offending = "lives under the audit log's retention policy"

        assert offending not in source


def _shipped() -> list[Any]:
    datasets: list[Any] = []
    for directory in (
        REPO / "agents/care/src/neura_agent_care/evals/datasets",
        REPO / "agents/sell/src/neura_agent_sell/evals/datasets",
    ):
        if directory.exists():
            datasets.extend(load_all(directory))
    return datasets


class TestTheSevenRemovedCases:
    def test_no_graded_case_survives_without_evidence(self) -> None:
        """[ADR-0034] §11. The seven promoted on 2026-09-06 predate capture and
        are not recoverable faithfully — every entity they cited had already
        moved. They were removed in git with the reason in the commit message,
        which is ADR-0032 §9's own rule applied to its own output.

        This asserts the *invariant*, not the removal: any graded case that
        exists must replay captured evidence.
        """
        for dataset in _shipped():
            if dataset.name != "graded":
                continue
            for case in dataset.cases:
                assert case.fixture_mode is FixtureMode.REPLAY, (
                    f"{case.id} is a promoted case that does not replay its evidence"
                )
                assert case.evidence, f"{case.id} names no evidence artefact"

    def test_the_dataset_header_warns_against_hand_writing(self) -> None:
        for path in (
            REPO / "agents/care/src/neura_agent_care/evals/datasets/graded.yaml",
            REPO / "agents/sell/src/neura_agent_sell/evals/datasets/graded.yaml",
        ):
            if not path.exists():
                continue
            header = str((yaml.safe_load(path.read_text()) or {}).get("description", ""))
            assert "DO NOT hand-write" in header


class TestAnArtefactMustProveItIsIntact:
    """[ADR-0034] §4 — a content address that is never checked is a filename.

    The failure this guards is the worst one available to this design: an
    artefact edited in place changes what a `synthetic: false` case asserts,
    while still looking exactly like evidence a human approved.
    """

    def _write(self, directory: Path, payload: dict[str, Any], name: str | None = None) -> str:
        content_hash = str(payload["_content_hash"])
        path = artefact_path(directory, name or content_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
        return name or content_hash

    def test_an_untouched_artefact_reads(self, tmp_path: Path) -> None:
        payload = export_artefact(_bundle())
        name = self._write(tmp_path, payload)

        assert read_artefact(tmp_path, name).calls

    def test_the_hash_is_reproducible_from_the_exported_file_alone(self) -> None:
        """The property that makes it content-addressed rather than just named.

        `store_id` is excluded from the identity precisely so that this holds:
        the exported file never carries it, so an identity that included it
        could not be recomputed from the file.
        """
        payload = export_artefact(_bundle())

        assert load_artefact(payload).content_hash() == payload["_content_hash"]

    def test_two_stores_with_identical_content_share_one_artefact(self) -> None:
        """The other half of excluding `store_id`, stated as behaviour."""
        one = export_artefact(_bundle(store_id="st_one"))
        two = export_artefact(_bundle(store_id="st_two"))

        assert one["_content_hash"] == two["_content_hash"]

    def test_the_clock_is_not_part_of_replay_identity(self) -> None:
        early = _bundle(captured_at=datetime(2026, 9, 1, tzinfo=UTC))
        late = _bundle(captured_at=datetime(2026, 9, 6, tzinfo=UTC))

        assert early.content_hash() == late.content_hash()

    def test_an_additive_schema_change_does_not_invalidate_an_artefact(
        self, tmp_path: Path
    ) -> None:
        """The bug this replaced, pinned so it cannot come back.

        The hash was taken over `model_dump()`, so adding one optional field to
        `RetrievalEvidence` gave every *already written* artefact a recomputed
        hash containing a `"diagnosis": null` the file did not have — and a
        promoted case nobody had touched failed its own integrity check.

        Simulated by writing a file with a key this version does not know: an
        older or newer artefact must still verify, because the hash covers the
        keys the file has rather than the keys the model currently declares.
        """
        payload = export_artefact(_bundle())
        payload["some_field_added_later"] = {"not": "in REPLAY_KEYS"}
        name = self._write(tmp_path, payload)

        assert read_artefact(tmp_path, name).calls, "an unknown key broke verification"

    def test_edited_content_is_refused(self, tmp_path: Path) -> None:
        """The tampering case. A price changed by hand must not run."""
        payload = export_artefact(_bundle())
        payload["entities"]["products"][0]["title"] = "A Product Nobody Approved"
        name = self._write(tmp_path, payload)

        with pytest.raises(EvidenceError, match="has been modified"):
            read_artefact(tmp_path, name)

    def test_an_edited_recorded_call_is_refused(self, tmp_path: Path) -> None:
        """Editing what the *store answered* is the subtle version of the same
        attack, and it is what a replay actually reads."""
        payload = export_artefact(_bundle())
        payload["calls"][0]["result"] = {"items": [{"external_id": "9999"}], "next_cursor": None}
        name = self._write(tmp_path, payload)

        with pytest.raises(EvidenceError, match="has been modified"):
            read_artefact(tmp_path, name)

    def test_a_renamed_artefact_is_refused(self, tmp_path: Path) -> None:
        """The filename and the embedded hash must agree."""
        payload = export_artefact(_bundle())
        name = self._write(tmp_path, payload, name="0" * 64)

        with pytest.raises(EvidenceError, match="was requested as"):
            read_artefact(tmp_path, name)

    def test_a_rewritten_embedded_hash_is_refused(self, tmp_path: Path) -> None:
        """The obvious way to defeat a one-sided check: edit the content, then
        edit the hash to match the filename."""
        payload = export_artefact(_bundle())
        original = str(payload["_content_hash"])
        payload["entities"]["products"][0]["title"] = "Edited"
        payload["_content_hash"] = original
        self._write(tmp_path, payload, name=original)

        with pytest.raises(EvidenceError, match="has been modified"):
            read_artefact(tmp_path, original)

    def test_the_error_says_which_file_and_both_hashes(self, tmp_path: Path) -> None:
        """A diagnostic nobody can act on is a failure that gets ignored."""
        payload = export_artefact(_bundle())
        payload["tools"] = ["something_else"]
        name = self._write(tmp_path, payload)

        with pytest.raises(EvidenceError) as caught:
            read_artefact(tmp_path, name)

        assert name[:16] in str(caught.value)
