"""What the developer MCP teaches (ADR-0053 §4, §5): every word checked against the code.

The teacher is only worth having if it cannot teach something wrong. So each
claim it makes is tied to the thing it describes: the formats to
``build_openapi()``, every sample to NEURA's own reader of bridge answers (the
real ``GenericAdapter``, over a fake shop that serves the samples), the
capability words to what CARE's and SELL's tools require, the status words to
the enums. A change to any of those fails here until the teacher says it too.

Test data stays platform-neutral, like the rest of the generic adapter's tests.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from neura_adapters.generic import GenericAdapter, teacher
from neura_adapters.generic.spec import build_openapi
from neura_adapters.generic.wire import SPEC_VERSION
from neura_agent_care.tools import build_registry as care_registry
from neura_agent_sell.tools import build_registry as sell_registry
from neura_commerce import SyncQuery
from neura_core.tenancy.customer_pass import (
    CUSTOMER_SECRET_PREFIX,
    MAX_PASS_LIFETIME,
    PASS_ALGORITHM,
    PASS_CLAIMS,
)
from neura_domain import (
    Capability,
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    PolicyKind,
    ProductStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-shop-token"


def _platform_names() -> tuple[str, ...]:
    """Rule 1's own list, read from the check that enforces it."""
    path = REPO_ROOT / "scripts" / "check_platform_independence.py"
    spec = importlib.util.spec_from_file_location("platform_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.PLATFORM_NAMES)


def _everything_it_says() -> list[dict[str, Any]]:
    """Every answer the teacher can give, for the checks that apply to all of them."""
    return [
        teacher.list_addresses(),
        teacher.get_rules(),
        teacher.get_openapi(),
        *(teacher.get_address(address.path) for address in teacher.ADDRESSES),
        *(teacher.get_rules(rule.topic) for rule in teacher.RULES),
    ]


# ── It covers the whole format, and only the format ──────────────────────────


def test_it_teaches_every_address_in_the_openapi_file() -> None:
    taught = {address.path for address in teacher.ADDRESSES}
    assert taught == set(build_openapi()["paths"])


def test_get_openapi_is_the_published_file() -> None:
    published = json.loads((REPO_ROOT / "docs" / "spec" / "openapi.json").read_text())
    assert teacher.get_openapi()["openapi"] == published


def test_each_address_carries_its_own_format_from_the_openapi_file() -> None:
    document = build_openapi()
    for address in teacher.ADDRESSES:
        answer = teacher.get_address(address.path)
        assert answer["request"] == document["paths"][address.path]["get"]
        # Every schema the answer refers to is handed over with it.
        refs = set(_refs(answer["request"]))
        while refs - set(answer["schemas"]):
            missing = refs - set(answer["schemas"])
            pytest.fail(f"{address.path}: schemas not handed over: {sorted(missing)}")
        for name in answer["schemas"]:
            assert answer["schemas"][name] == document["components"]["schemas"][name]


def _refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        found = []
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value.rsplit("/", 1)[-1])
            else:
                found.extend(_refs(value))
        return found
    if isinstance(node, list):
        return [ref for item in node for ref in _refs(item)]
    return []


# ── Every sample is a real, working answer ───────────────────────────────────


def _fake_shop() -> httpx.MockTransport:
    """A shop that answers each sample request with its sample answer."""
    answers: dict[tuple[str, str], Any] = {}
    for address in teacher.ADDRESSES:
        parts = urlsplit(address.sample_request)
        answers[(parts.path, parts.query)] = address.sample

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/neura/v1")
        if path != "/health" and request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": "token"})
        for (sample_path, _query), body in answers.items():
            if sample_path == path:
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _adapter() -> GenericAdapter:
    return GenericAdapter(
        base_url="https://yourshop.example/neura/v1",
        tenant_id="tn_teacher_test",
        token=TOKEN,
        transport=_fake_shop(),
    )


def _sample(path: str) -> Any:
    return next(a.sample for a in teacher.ADDRESSES if a.path == path)


async def test_every_sample_is_read_by_neura_as_it_reads_a_real_bridge() -> None:
    adapter = _adapter()

    health = await adapter.health()
    assert health.ok
    assert {c.value for c in health.capabilities} == set(_sample("/health")["capabilities"])

    page = await adapter.list_products(SyncQuery())
    assert [p.external_id for p in page.items] == ["1042"]

    product = await adapter.get_product("1042")
    assert product is not None
    assert product.status is ProductStatus.ACTIVE
    assert [(v.external_id, v.in_stock) for v in product.variants] == [
        ("1042-m", True),
        ("1042-l", False),
    ]

    categories = await adapter.list_categories()
    assert {c.external_id for c in categories} == {"3", "12"}

    stock = await adapter.get_inventory(["1042-m", "1042-l"])
    assert [(s.variant_external_id, s.in_stock) for s in stock] == [
        ("1042-m", True),
        ("1042-l", False),
    ]

    orders = await adapter.list_orders(SyncQuery())
    assert [o.order_number for o in orders.items] == ["1001"]

    order = await adapter.get_order("5001")
    assert order is not None
    assert order.status is OrderStatus.SHIPPED
    assert order.fulfillments and order.fulfillments[0].tracking_number

    customer = await adapter.get_customer("77")
    assert customer is not None
    assert customer.email == "ana@example.com"

    policies = await adapter.get_policies()
    assert {p.kind for p in policies} == {PolicyKind.RETURNS, PolicyKind.SHIPPING}


def test_no_sample_has_a_field_the_format_does_not_know() -> None:
    """NEURA's reader drops an unknown field quietly, so the reader alone cannot
    catch a sample that teaches a made-up field. The OpenAPI file can."""
    schemas = build_openapi()["components"]["schemas"]
    for address in teacher.ADDRESSES:
        response = build_openapi()["paths"][address.path]["get"]["responses"]["200"]
        schema = response["content"]["application/json"]["schema"]
        unknown = _unknown_fields(address.sample, schema, schemas, address.path)
        assert unknown == [], f"{address.path}: {unknown}"


def _unknown_fields(
    value: Any, schema: dict[str, Any], schemas: dict[str, Any], at: str
) -> list[str]:
    if "$ref" in schema:
        return _unknown_fields(value, schemas[schema["$ref"].rsplit("/", 1)[-1]], schemas, at)
    for option in schema.get("anyOf", []):
        if option.get("type") == "null":
            continue
        if isinstance(value, dict) == ("properties" in option or "$ref" in option):
            return _unknown_fields(value, option, schemas, at)
    if isinstance(value, list):
        item = schema.get("items", {})
        return [
            u for i, v in enumerate(value) for u in _unknown_fields(v, item, schemas, f"{at}[{i}]")
        ]
    if isinstance(value, dict) and "properties" in schema:
        known = schema["properties"]
        found = [f"{at}.{key}" for key in value if key not in known]
        for key, inner in value.items():
            if key in known:
                found.extend(_unknown_fields(inner, known[key], schemas, f"{at}.{key}"))
        return found
    return []


def test_the_product_sample_is_the_one_the_guide_shows() -> None:
    """Step 1 of the developer guide shows the same product (A10)."""
    guide = (REPO_ROOT / "apps/neura-web/src/app/docs/developers/page.tsx").read_text()
    shown = guide.split("const SAMPLE_PRODUCT = `", 1)[1].split("`;", 1)[0]
    assert json.loads(shown) == _sample("/products/{id}")


# ── The words come from the code ─────────────────────────────────────────────


def test_every_word_an_assistant_needs_is_taught_with_its_address() -> None:
    required = {
        c for registry in (care_registry(), sell_registry()) for t in registry for c in t.requires
    }
    taught = {c for address in teacher.ADDRESSES for c in address.capabilities}
    assert required <= taught


def test_every_capability_word_is_either_taught_or_ruled_out() -> None:
    taught = {c for address in teacher.ADDRESSES for c in address.capabilities}
    taught |= set(teacher.EXTRA_CAPABILITIES)
    left_out = set(teacher.LEAVE_OUT)
    assert taught | left_out == set(Capability)
    assert not taught & left_out
    rules = json.dumps(teacher.get_rules())
    for capability in left_out:
        assert capability.value in rules


@pytest.mark.parametrize(
    "vocabulary", [ProductStatus, OrderStatus, PaymentStatus, FulfillmentStatus]
)
def test_every_status_word_is_taught(vocabulary: type) -> None:
    rules = json.dumps(teacher.get_rules())
    for member in vocabulary:
        assert f'"{member.value}"' in rules.replace('\\"', '"'), member


# ── What it must never say ───────────────────────────────────────────────────


def test_no_platform_name_in_anything_it_teaches() -> None:
    said = json.dumps(_everything_it_says()).lower()
    for name in _platform_names():
        assert name not in said, name


def test_it_never_sends_a_developer_to_a_tool_they_cannot_get() -> None:
    """G70: the check tool exists only inside our code (G10)."""
    assert "neura-conformance" not in json.dumps(_everything_it_says())


def test_it_says_not_to_build_webhooks_to_neura_yet() -> None:
    """G66: the OpenAPI file describes them, and NEURA has no address that
    receives them. The file and the rules say the same."""
    webhook = build_openapi()["webhooks"]["entityChanged"]["post"]
    assert webhook["description"].startswith("Not used yet")
    assert "events.realtime" in json.dumps(teacher.get_rules("webhooks"))


# ── Order questions from signed-in shoppers (ADR-0057) ───────────────────────


def _customer_pass_rule() -> str:
    answer = teacher.get_rules("customer-pass")
    return str(answer["rules"][0]["text"])


def test_it_teaches_the_customer_pass_as_neura_checks_it() -> None:
    """Every number and name in the rule is the one `check_customer_pass` uses:
    a developer's AI tool that makes a pass from this rule makes one NEURA
    accepts."""
    text = _customer_pass_rule()
    assert PASS_ALGORITHM in text
    for claim in PASS_CLAIMS:
        assert f'"{claim}"' in text, claim
    assert f"{int(MAX_PASS_LIFETIME.total_seconds() // 60)} minutes" in text
    assert CUSTOMER_SECRET_PREFIX in text
    # A number is refused (G83), and the reason says so the same way.
    assert '"385", not 385' in text


def test_it_names_the_chat_box_settings_the_chat_box_reads() -> None:
    text = _customer_pass_rule()
    widget = (REPO_ROOT / "apps/neura-api/src/neura_api/widget/widget.js").read_text()
    for attribute, read_as in (
        ("data-neura-customer-pass", "data.neuraCustomerPass"),
        ("data-neura-sign-in-url", "data.neuraSignInUrl"),
    ):
        assert attribute in text, attribute
        assert read_as in widget, read_as


def test_it_carries_the_security_reviews_two_rules_as_the_guide_does() -> None:
    """ADR-0057's security review, rows 5 and 6: nothing NEURA can check, so
    they are rules for the developer, here and in the guide."""
    text = _customer_pass_rule().lower()
    guide = (REPO_ROOT / "apps/neura-web/src/app/docs/developers/page.tsx").read_text().lower()
    for rule in ("cache-control: private, no-store", "never from anything in the request"):
        assert rule in text, rule
        assert rule in guide, rule


@pytest.mark.parametrize("path", ["/orders", "/orders/{id}", "/customers/{id}"])
def test_the_order_addresses_point_to_the_customer_pass(path: str) -> None:
    topics = [rule["topic"] for rule in teacher.get_address(path)["rules"]]
    assert "customer-pass" in topics


# ── Versions and unknown questions ───────────────────────────────────────────


def test_every_answer_names_the_format_version_it_teaches() -> None:
    for answer in _everything_it_says():
        assert answer["format_version"] == SPEC_VERSION


def test_a_version_it_does_not_teach_is_refused() -> None:
    with pytest.raises(teacher.UnknownVersionError):
        teacher.list_addresses(version="9.9")


def test_an_address_it_does_not_know_is_refused() -> None:
    with pytest.raises(teacher.UnknownAddressError):
        teacher.get_address("/carts")


def test_a_topic_it_does_not_know_is_refused() -> None:
    with pytest.raises(teacher.UnknownTopicError):
        teacher.get_rules("discounts")
