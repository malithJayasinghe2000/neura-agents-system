"""The widget: hosting, per-tenant CORS, and the withheld-turn contract.

Three groups, and the third is the one that matters most. ADR-0020 says a
withheld reply must arrive with the words to say instead, and the whole reason
that is a *server* decision rather than a client convention is so it can be
asserted here — once, against both transports, rather than trusted to whoever
writes the next client.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neura_agent_core.conversations import ConversationState
from neura_agent_core.serving import TurnOutcome
from neura_api.main import create_app
from neura_api.middleware.cors import is_valid_origin
from neura_api.turns import TurnResult
from neura_core import get_settings
from neura_core.tenancy import TenantConfig, TurnMode
from neura_core.tenancy.keys import ApiKeyKind, generate

WIDGET_JS = Path(__file__).parents[2] / "apps/neura-api/src/neura_api/widget/widget.js"


def _code_only(source: str) -> str:
    """The widget's source with its comments removed.

    Needed because these assertions are about what the code *does*, and a check
    a comment can trip is a check that gets satisfied by rewording the comment
    explaining why the thing is forbidden.
    """
    lines = []
    in_block = False
    for line in source.splitlines():
        stripped = line.strip()
        if in_block:
            in_block = not stripped.endswith("*/")
            continue
        if stripped.startswith("/*"):
            in_block = not stripped.endswith("*/")
            continue
        if stripped.startswith("//"):
            continue
        lines.append(line.split("//")[0] if "://" not in line else line)
    return "\n".join(lines)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _result(
    *, mode: TurnMode, reply: str, withheld: str = "Nothing automated is available."
) -> TurnResult:
    return TurnResult(
        conversation_id="cnv_1",
        message_id="msg_1",
        outcome=TurnOutcome(reply=reply, state=ConversationState.RESOLVED),
        policy=None,  # type: ignore[arg-type]
        started_conversation=True,
        mode=mode,
        withheld_message=withheld,
    )


class TestAWithheldTurnIsNeverEmptyHanded:
    """ADR-0020. The invariant, stated where both transports read it."""

    def test_a_shadowed_turn_withholds_the_reply_and_supplies_words(self) -> None:
        result = _result(mode=TurnMode.SHADOW, reply="Your order shipped on 22 July.")
        # 1.15's decision, unchanged: the draft does not reach the shopper.
        assert result.reply == ""
        # ADR-0020's addition: and they are not shown nothing.
        assert result.fallback_message == "Nothing automated is available."

    def test_a_live_turn_carries_no_fallback(self) -> None:
        """Otherwise a client rendering `reply or fallback_message` would show
        both, or show the fallback on a turn that was answered perfectly well."""
        result = _result(mode=TurnMode.LIVE, reply="Your order shipped on 22 July.")
        assert result.reply == "Your order shipped on 22 July."
        assert result.fallback_message == ""

    def test_the_reply_and_the_fallback_are_never_both_present(self) -> None:
        for mode in (TurnMode.LIVE, TurnMode.SHADOW):
            result = _result(mode=mode, reply="something")
            assert not (result.reply and result.fallback_message)

    def test_the_fallback_is_never_the_withheld_draft(self) -> None:
        """The draft is the one thing this field must not become.

        A field that showed the shopper what the agent would have said would
        undo shadow mode entirely — and would do it through a path where no
        `verify` result is consulted, because the text is chosen after the turn.
        """
        result = _result(mode=TurnMode.SHADOW, reply="Your order shipped on 22 July.")
        assert "22 July" not in result.fallback_message

    def test_the_platform_default_promises_nothing(self) -> None:
        """The A9(3) failure, shipped as a platform string, is the thing to avoid.

        A shadow turn emits no webhook and there is no console anybody watches,
        so a default about a colleague getting in touch would be an offer
        nothing can honour — on the one path where no verifier runs, because no
        model ran.
        """
        default = get_settings().widget_withheld_message.lower()
        for promise in ("get back to you", "will be in touch", "our team", "someone will"):
            assert promise not in default

    def test_a_tenant_may_override_the_wording(self) -> None:
        config = TenantConfig.model_validate({"withheld_message": "We are reading this ourselves."})
        assert config.withheld_message == "We are reading this ourselves."

    def test_an_unconfigured_tenant_has_none_and_not_an_empty_string(self) -> None:
        """`None` means "use the platform default"; `""` would mean "say nothing",
        which is exactly the outcome ADR-0020 exists to prevent."""
        assert TenantConfig().withheld_message is None


class TestBothTransportsCarryTheSameFields:
    """ADR-0019 §4 accepts two transports; it does not accept two contracts.

    The widget renders from one function, so a field present on one path and
    absent on the other is a widget that behaves differently depending on
    whether a socket happened to open.
    """

    def test_the_chat_response_model_declares_the_fallback(self) -> None:
        from neura_api.routes.agent import ChatData

        assert "fallback_message" in ChatData.model_fields

    def test_the_socket_done_frame_declares_the_fallback(self) -> None:
        source = Path(__file__).parents[2] / "apps/neura-api/src/neura_api/stream.py"
        body = source.read_text(encoding="utf-8")
        assert '"fallback_message": result.fallback_message' in body

    def test_neither_transport_reads_the_outcome_reply_directly(self) -> None:
        """`TurnResult.reply` is the only safe reader — see its docstring."""
        for name in ("stream.py", "routes/agent.py"):
            source = Path(__file__).parents[2] / "apps/neura-api/src/neura_api" / name
            assert "outcome.reply" not in source.read_text(encoding="utf-8")


class TestWidgetHosting:
    def test_the_asset_is_served_from_our_own_origin(self, client: TestClient) -> None:
        response = client.get("/v1/widget/widget.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
        assert "neura-chat" in response.text

    def test_the_asset_is_public(self, client: TestClient) -> None:
        """No key, no 401. It is code served to every shopper on every site, and
        a `<script src>` cannot present a credential anyway."""
        assert client.get("/v1/widget/widget.js").status_code == 200

    def test_the_asset_is_not_sniffable(self, client: TestClient) -> None:
        headers = client.get("/v1/widget/widget.js").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert "max-age=300" in headers["cache-control"]

    def test_the_pairing_block_is_served_the_same_way(self, client: TestClient) -> None:
        """ADR-0040's client half, hosted exactly as the widget is.

        **A separate asset rather than more of `widget.js`**: a merchant who
        wants suggestions on a cart page and no chat box must not be made to
        ship a chat widget, and a shopper on that page must not download one.
        """
        response = client.get("/v1/widget/pairs.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "neura-pairs" in response.text

    def test_the_two_assets_are_genuinely_separate(self, client: TestClient) -> None:
        """A chat box must not arrive with a suggestion block."""
        assert "neura-chat" not in client.get("/v1/widget/pairs.js").text

    def test_the_pairing_block_never_claims_behaviour(self, client: TestClient) -> None:
        """ADR-0040 §3 rules these out by name, and the shipped file is the
        artefact — there is no build step between this and a shopper's screen,
        so the published bytes are the right thing to assert against.

        Checked outside comments, because this file argues at length about
        exactly the phrases it must never render.
        """
        import re

        source = client.get("/v1/widget/pairs.js").text
        code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)

        for claim in ("bought together", "customers also", "trending", "popular"):
            assert claim not in code.lower()

    def test_the_snippet_names_the_key_and_the_hosted_url(self, client: TestClient) -> None:
        body = client.get("/v1/widget/snippet?key=fn_pk_test_abc").json()
        assert "fn_pk_test_abc" in body["snippet"]
        assert body["widget_url"].endswith("/v1/widget/widget.js")

    def test_the_snippet_offers_both_surfaces_separately(self, client: TestClient) -> None:
        """A merchant who wants suggestions and no chat box must be able to see
        that these are two pastes, rather than learning it from support."""
        body = client.get("/v1/widget/snippet?key=fn_pk_test_abc").json()
        assert body["pairs_url"].endswith("/v1/widget/pairs.js")
        assert "neura-pairs" in body["pairs_snippet"]
        assert "fn_pk_test_abc" in body["pairs_snippet"]
        assert "neura-pairs" not in body["snippet"]

    def test_the_snippet_names_the_developer_mcp_on_the_same_address(
        self, client: TestClient
    ) -> None:
        """ADR-0053 §6: Help names the address a developer's AI tool uses. It is
        made where the chat box line's is, from the API's own public address, so
        the dashboard never builds an address of its own, and it is the address
        the developer MCP is really mounted at."""
        from neura_api.developer_mcp import ENDPOINT, MOUNT

        body = client.get("/v1/widget/snippet").json()
        origin = body["widget_url"].removesuffix("/v1/widget/widget.js")
        assert body["developer_mcp_url"] == f"{origin}{MOUNT}{ENDPOINT}"

        given = client.get("/v1/widget/snippet?base=https://neura.example/").json()
        assert given["developer_mcp_url"] == "https://neura.example/v1/developers/mcp"

    def test_the_pairing_snippet_asks_for_product_ids_and_not_a_cart(
        self, client: TestClient
    ) -> None:
        """ADR-0040 §2. The attribute is named for what it holds; a snippet
        saying `data-cart` would make the tenth endpoint feel natural."""
        snippet = client.get("/v1/widget/snippet?key=fn_pk_test_abc").json()["pairs_snippet"]
        assert "data-products" in snippet
        assert "cart" not in snippet.lower()

    def test_the_demo_page_strips_anything_but_a_key(self, client: TestClient) -> None:
        """The key lands in an attribute value on a page whose job is to load a
        script, so anything that could close the attribute is removed."""
        response = client.get('/v1/widget/demo?key=x"><script>alert(1)</script>')
        assert response.status_code == 200
        assert "<script>alert" not in response.text
        assert 'data-neura-key="xscriptalert1script"' in response.text


class TestTheWidgetShipsAsItsOwnSource:
    """ADR-0019 §1. No build step, so what a browser runs is this file."""

    def test_there_is_no_javascript_toolchain(self) -> None:
        """No build step anywhere the WIDGET can reach.

        **Narrowed on 2026-08-27, and narrowed rather than deleted.** The
        merchant console is a Next.js application under `apps/neura-console`
        ([ADR-0026](../../docs/architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md)),
        so a `package.json` now exists in this repository — deliberately, with an
        ADR, which is precisely the condition the original assertion's own
        message named.

        What it protected is untouched and is what still matters: the widget is
        pasted into a merchant's own page, so **what a browser runs must be the
        file in this repository** and not the output of a toolchain nobody
        reviews (ADR-0019 §1). The console is served by us, to a merchant, and
        carries none of that argument.

        The exclusion is a list of named directories rather than a pattern, so
        the next `package.json` to appear anywhere else still fails this test.
        **The second, 2026-09-30:** the public website, `apps/neura-web`
        ([ADR-0051](../../docs/architecture/adr/0051-the-public-website-is-its-own-app-and-says-only-what-the-code-does.md)).
        Served by us as static pages, never pasted into a merchant's page — the
        console's argument, not the widget's.
        """
        root = Path(__file__).parents[2]
        allowed = (root / "apps" / "neura-console", root / "apps" / "neura-web")
        stray = [
            p
            for p in root.rglob("package.json")
            if ".venv" not in p.parts
            and "node_modules" not in p.parts
            and not any(app in p.parents for app in allowed)
        ]
        assert stray == [], f"a JS toolchain appeared without an ADR: {stray}"

    def test_the_element_needs_no_imports(self) -> None:
        source = _code_only(WIDGET_JS.read_text(encoding="utf-8"))
        assert "import " not in source
        assert "require(" not in source

    def test_nothing_is_rendered_as_markup(self) -> None:
        """Everything the widget renders came off the network — a shopper's own
        words, a merchant's policy text, a model's reply. None of it is markup
        we authored, so none of it goes near innerHTML."""
        source = _code_only(WIDGET_JS.read_text(encoding="utf-8"))
        assert "innerHTML" not in source
        assert "outerHTML" not in source
        assert "document.write" not in source
        assert "eval(" not in source

    def test_the_served_asset_is_the_file_on_disk(self, client: TestClient) -> None:
        assert client.get("/v1/widget/widget.js").text == WIDGET_JS.read_text(encoding="utf-8")


class TestPerTenantCors:
    """ADR-0019 §3. The presented key decides, and preflight decides nothing."""

    def test_a_preflight_is_answered_for_any_valid_origin(self, client: TestClient) -> None:
        """It authorises a browser to *send*, never to read. The request it
        permits is still refused by the key's own origin lock."""
        response = client.options(
            "/v1/care/chat",
            headers={
                "Origin": "https://a-shop-we-have-never-heard-of.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 204
        allowed = response.headers["access-control-allow-origin"]
        assert allowed == "https://a-shop-we-have-never-heard-of.example"

    def test_a_preflight_promises_only_what_a_real_request_honours(
        self, client: TestClient
    ) -> None:
        response = client.options(
            "/v1/care/chat",
            headers={"Origin": "https://shop.example", "Access-Control-Request-Method": "POST"},
        )
        assert "Idempotency-Key" in response.headers["access-control-allow-headers"]
        assert "POST" in response.headers["access-control-allow-methods"]
        assert response.headers["vary"] == "Origin"

    def test_an_unauthenticated_response_carries_no_allow_origin(self, client: TestClient) -> None:
        """The half that actually protects anything: a cross-origin request from
        an origin the key does not permit is unreadable in the browser, and its
        refusal is not an oracle for whether the key is valid somewhere else."""
        response = client.post(
            "/v1/care/chat",
            headers={"Origin": "https://not-a-tenant.example", "Authorization": "Bearer fn_pk_x"},
            json={"message": "hello"},
        )
        assert response.status_code in {401, 403}
        assert "access-control-allow-origin" not in response.headers

    @pytest.mark.parametrize("path", ["/v1/chat", "/v1/care/chat"])
    def test_a_secret_key_from_a_web_page_is_refused_and_says_why(
        self, client: TestClient, path: str
    ) -> None:
        """G55: a secret key put in the chat box line used to work, through the
        plain-request fallback, while anyone could read it in the page. It is
        now refused on its shape, before any lookup, and this one refusal is
        readable: the page learns nothing it did not send, and the chat box can
        say what is wrong instead of the browser's "Failed to fetch"."""
        secret = generate(ApiKeyKind.SECRET).token
        response = client.post(
            path,
            headers={"Origin": "https://shop.example", "Authorization": f"Bearer {secret}"},
            json={"message": "hello"},
        )
        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "SECRET_KEY_IN_PAGE"
        assert "fn_pk_" in error["message"]
        assert response.headers["access-control-allow-origin"] == "https://shop.example"

    def test_an_unkeyed_endpoint_falls_back_to_the_platform_list(self, client: TestClient) -> None:
        allowed = get_settings().widget_origins[0]
        response = client.get("/v1/health", headers={"Origin": allowed})
        assert response.headers.get("access-control-allow-origin") == allowed

        refused = client.get("/v1/health", headers={"Origin": "https://elsewhere.example"})
        assert "access-control-allow-origin" not in refused.headers

    @pytest.mark.parametrize(
        "origin",
        [
            None,
            "",
            # A sandboxed iframe or a file:// page. Every such page shares it, so
            # it is the one string that cannot identify anybody.
            "null",
            "not-a-url",
            "ftp://shop.example",
            # A URL somebody pasted rather than an origin a browser sent —
            # echoing it would put attacker-chosen text into a header.
            "https://shop.example/path",
            "https://shop.example?q=1",
        ],
    )
    def test_a_non_origin_is_never_reflected(self, origin: str | None) -> None:
        assert not is_valid_origin(origin)

    def test_a_real_origin_is_accepted(self) -> None:
        assert is_valid_origin("https://shop.example")
        assert is_valid_origin("http://localhost:3000")


class TestTheDemoPageDoesNotChooseTheAgent:
    """[ADR-0031] §1 — and the one place the fix was missed.

    `widget.js` stopped defaulting to `care` on 2026-09-01. The demo route did
    not, so the one page anybody actually opens in a browser wrote
    ``data-neura-agent="care"`` into every page it served, pinned every message
    to CARE, and dispatch never ran. Found by the project owner typing into the
    demo widget and getting the same agent for everything — which is A13's own
    defect, reintroduced one layer above the fix.

    A page that renders `.js` correctly and then hardcodes what it passes to it
    is a page whose correctness is not covered by the `.js` tests.
    """

    def test_no_agent_is_pinned_by_default(self, client: TestClient) -> None:
        body = client.get("/v1/widget/demo", params={"key": "fn_pk_test_abc"}).text
        assert 'data-neura-agent=""' in body

    def test_an_explicit_agent_is_still_honoured(self, client: TestClient) -> None:
        """The demo is how a single-agent embed gets driven by hand."""
        body = client.get("/v1/widget/demo", params={"key": "fn_pk_test_abc", "agent": "sell"}).text
        assert 'data-neura-agent="sell"' in body

    def test_a_junk_agent_falls_back_to_dispatch_not_to_care(self, client: TestClient) -> None:
        """The sanitiser used to end in `or "care"`, which is the same bug again.

        A parameter that survives stripping as empty must mean "let the server
        choose", not "silently use one particular agent".
        """
        body = client.get("/v1/widget/demo", params={"key": "fn_pk_test_abc", "agent": "<>/"}).text
        assert 'data-neura-agent=""' in body
