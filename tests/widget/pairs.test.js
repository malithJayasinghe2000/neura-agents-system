/**
 * The paired-suggestion block's pure logic, run with `node --test`.
 *
 * Same arrangement as `widget.test.js` and for the same reason: no
 * package.json, no install, no lockfile. Run it with `make test-widget`.
 *
 * The surface under test is the half that decides what a shopper is shown —
 * reading the element's configuration, and turning a response into a block or
 * into nothing. Everything else in that file is DOM, and the rules worth
 * protecting are all above it.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const pairs = require(
  path.join(__dirname, "../../apps/neura-api/src/neura_api/widget/pairs.js")
);

test("a comma-separated attribute becomes a list of ids", () => {
  const config = pairs.configFrom(element({ "data-products": "1315,1332" }), "");
  assert.deepStrictEqual(config.productIds, ["1315", "1332"]);
});

test("spaces and a trailing comma are tolerated", () => {
  // A theme building this attribute in a template loop produces exactly this,
  // and a surface that 400s on it is a surface nobody ships.
  const config = pairs.configFrom(element({ "data-products": " 1315 , 1332 , " }), "");
  assert.deepStrictEqual(config.productIds, ["1315", "1332"]);
});

test("a repeated id is sent once", () => {
  const config = pairs.configFrom(element({ "data-products": "1315,1315" }), "");
  assert.deepStrictEqual(config.productIds, ["1315"]);
});

test("a very long page does not spend the bytes", () => {
  const many = Array.from({ length: 40 }, (_, n) => `id_${n}`).join(",");
  const config = pairs.configFrom(element({ "data-products": many }), "");
  assert.strictEqual(config.productIds.length, pairs.MAX_IDS);
});

test("the API base defaults to wherever the script was served from", () => {
  const base = pairs.baseFrom("", "https://api.example.com/v1/widget/pairs.js");
  assert.strictEqual(base, "https://api.example.com");
});

test("an explicit API base wins over the script's own origin", () => {
  const base = pairs.baseFrom("https://neura.example.com/", "https://cdn.example.com/v1/widget/pairs.js");
  assert.strictEqual(base, "https://neura.example.com");
});

test("no suggestions renders nothing, not an empty box", () => {
  assert.strictEqual(pairs.blockFor({ heading: "Goes well with your Rain Shell", suggestions: [] }), null);
});

test("a response with no heading renders nothing", () => {
  // ADR-0040 §3: with three items on a page, an unlabelled "goes well with"
  // names nothing a shopper can judge or reject. No heading, no block.
  assert.strictEqual(pairs.blockFor({ suggestions: [{ id: "1", title: "A boot" }] }), null);
});

test("the heading is the server's words, never composed here", () => {
  const block = pairs.blockFor({
    heading: "Goes well with your Rain Shell",
    suggestions: [{ id: "1", title: "A boot" }],
  });
  assert.strictEqual(block.heading, "Goes well with your Rain Shell");
});

test("a card with nothing to name is dropped", () => {
  const block = pairs.blockFor({
    heading: "Goes well with your Rain Shell",
    suggestions: [{ id: "1", title: "A boot" }, { id: "2" }],
  });
  assert.strictEqual(block.cards.length, 1);
});

test("dropping every card leaves no block at all", () => {
  assert.strictEqual(
    pairs.blockFor({ heading: "Goes well with your Rain Shell", suggestions: [{ id: "2" }] }),
    null
  );
});

test("a price is never shown without its currency", () => {
  // A bare number beside a product is a price claim in whatever currency the
  // shopper assumes, which is a false claim we would have made ourselves.
  assert.strictEqual(pairs.priceText({ price: "18.00" }), "");
});

test("a javascript: url never reaches an attribute", () => {
  assert.strictEqual(pairs.safeUrl("javascript:alert(1)"), "");
});

test("a data: image never reaches an attribute", () => {
  assert.strictEqual(pairs.safeUrl("data:text/html,<script>alert(1)</script>"), "");
});

test("an ordinary product link survives", () => {
  assert.strictEqual(
    pairs.safeUrl("https://shop.example.com/p/1332"),
    "https://shop.example.com/p/1332"
  );
});

/** The two attributes the element actually reads. */
function element(attributes) {
  return {
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attributes, name) ? attributes[name] : null;
    },
  };
}
