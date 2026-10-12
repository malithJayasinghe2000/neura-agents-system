/**
 * The widget's pure logic, run with `node --test` (Node 24's built-in runner).
 *
 * No package.json, no install, no lockfile — ADR-0019 §1 keeps the monorepo
 * Python-only, and this is the whole cost of also testing the client. Run it
 * with `make test-widget`.
 *
 * The surface under test is deliberately small: the function that decides what
 * a completed turn renders. That is the ADR-0020 invariant, and it is the one
 * piece of client logic where being wrong shows a shopper nothing at all.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");

const widget = require(
  path.join(__dirname, "../../apps/neura-api/src/neura_api/widget/widget.js")
);

test("an answered turn renders the reply as the assistant", () => {
  const rows = widget.messagesForTurn({
    reply: "Your order #1001 shipped on 22 July.",
    state: "resolved",
    ai_disclosure: "You are chatting with an AI assistant.",
  });
  assert.deepStrictEqual(rows, [
    {
      role: "assistant",
      text: "Your order #1001 shipped on 22 July.",
      disclosure: "You are chatting with an AI assistant.",
    },
  ]);
});

test("a shadowed turn renders the server's words, not silence", () => {
  // 1.15 withholds the reply by design. Rendering `reply` alone would show an
  // empty bubble, which is the bug this whole decision exists to prevent.
  const rows = widget.messagesForTurn({
    reply: "",
    fallback_message: "Thanks — your message has been received.",
    state: "shadowed",
    ai_disclosure: "You are chatting with an AI assistant.",
  });
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].text, "Thanks — your message has been received.");
});

test("the withheld message is not dressed up as the assistant speaking", () => {
  // The agent did not say it: the merchant's configured wording did.
  const rows = widget.messagesForTurn({ reply: "", fallback_message: "No answer available." });
  assert.strictEqual(rows[0].role, "system");
});

test("the disclosure rides on every rendered turn, not just the first", () => {
  // EU AI Act Art. 50. The server sends it on every response for this reason,
  // so a client that dropped it after the first would defeat the point.
  const disclosure = "You are chatting with an AI assistant.";
  for (const payload of [
    { reply: "hello", ai_disclosure: disclosure },
    { reply: "", fallback_message: "withheld", ai_disclosure: disclosure },
  ]) {
    assert.strictEqual(widget.messagesForTurn(payload)[0].disclosure, disclosure);
  }
});

test("an empty turn with no fallback is an error, never silence", () => {
  // ADR-0020 §4. Silence is the one outcome indistinguishable from a bug, and
  // it is what a naive implementation defaults to.
  const rows = widget.messagesForTurn({ reply: "", fallback_message: "", state: "shadowed" });
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].role, "error");
  assert.strictEqual(rows[0].text, widget.EMPTY_TURN_MESSAGE);
  assert.ok(rows[0].text.length > 0);
});

test("a missing payload is an error rather than a crash", () => {
  for (const payload of [undefined, null, {}]) {
    const rows = widget.messagesForTurn(payload);
    assert.strictEqual(rows[0].role, "error");
  }
});

test("the error row carries no AI disclosure", () => {
  // The widget is speaking there, not the agent.
  const rows = widget.messagesForTurn({ reply: "", ai_disclosure: "You are chatting with an AI." });
  assert.strictEqual(rows[0].disclosure, "");
});

test("a reply and a fallback never render together", () => {
  const rows = widget.messagesForTurn({ reply: "answer", fallback_message: "withheld" });
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].text, "answer");
});

test("the API base defaults to the origin that served the widget", () => {
  // The API hosts the asset (ADR-0019 §2), so in the common case a merchant
  // configures nothing but the key.
  const config = widget.configFrom(
    {
      src: "https://api.example.com/v1/widget/widget.js",
      dataset: { neuraKey: "fn_pk_live_abc" },
    },
    { origin: "https://shop.example" }
  );
  assert.strictEqual(config.base, "https://api.example.com");
  assert.strictEqual(config.key, "fn_pk_live_abc");
  // No agent, so the server chooses ([ADR-0031]). This asserted "care" until
  // 2026-09-01, which is precisely the defect A13 records: a merchant who
  // configured nothing got one agent for every message forever, and a shop
  // paying for two could reach only one of them.
  assert.strictEqual(config.agent, "");
});

test("an explicit API base wins over the script's own origin", () => {
  const config = widget.configFrom(
    {
      src: "https://cdn.example.com/v1/widget/widget.js",
      dataset: { neuraKey: "k", neuraApi: "https://api.example.com/", neuraAgent: "sell" },
    },
    { origin: "https://shop.example" }
  );
  assert.strictEqual(config.base, "https://api.example.com");
  assert.strictEqual(config.agent, "sell");
});

test("endpoints are built per agent, and the socket swaps scheme", () => {
  assert.strictEqual(
    widget.endpointFor("https://api.example.com", "care", "chat"),
    "https://api.example.com/v1/care/chat"
  );
  assert.strictEqual(
    widget.endpointFor("https://api.example.com", "care", "stream"),
    "wss://api.example.com/v1/care/stream"
  );
  assert.strictEqual(
    widget.endpointFor("http://localhost:8000", "care", "stream"),
    "ws://localhost:8000/v1/care/stream"
  );
});

test("no agent means the dispatched door, on both transports", () => {
  // [ADR-0031]. The shopper never chooses, so the widget does not either: it
  // posts to `/v1/chat` and the server reads the merchant's enabled agents.
  assert.strictEqual(
    widget.endpointFor("https://api.example.com", "", "chat"),
    "https://api.example.com/v1/chat"
  );
  assert.strictEqual(
    widget.endpointFor("https://api.example.com", "", "stream"),
    "wss://api.example.com/v1/stream"
  );
});

test("a named agent still gets its own route", () => {
  // ADR-0031 adds a door; it closes none. An integrator who names an agent —
  // and every single-agent embed, which has nothing to dispatch — is unaffected.
  const config = widget.configFrom(
    { src: "https://api.example.com/v1/widget/widget.js",
      dataset: { neuraKey: "k", neuraAgent: "sell" } },
    { origin: "https://shop.example" }
  );
  assert.strictEqual(config.agent, "sell");
  assert.strictEqual(
    widget.endpointFor(config.base, config.agent, "chat"),
    "https://api.example.com/v1/sell/chat"
  );
});

test("an unknown graph node still produces a status line", () => {
  // Agent #2 will have nodes this file has never heard of, and it must not
  // need a widget change to show progress.
  assert.strictEqual(widget.labelForStep("verify"), "Checking the reply…");
  assert.strictEqual(widget.labelForStep("some_future_node"), widget.STEP_FALLBACK);
  assert.strictEqual(widget.labelForStep(undefined), widget.STEP_FALLBACK);
});

// ── Product cards ([ADR-0030]) ───────────────────────────────────────────────
//
// `productsForTurn` is tested for the same reason `messagesForTurn` is: it
// decides what a shopper is shown. The difference is that two of its fields
// become attributes a browser resolves, so being wrong here is not a blank
// bubble — it is a merchant's product URL executing on their own storefront.

test("a turn with products returns them as clean fields", () => {
  const items = widget.productsForTurn({
    reply: "The Waxed Cotton Field Jacket (1311) is 165.00 USD.",
    products: [
      {
        id: "1311",
        title: "Waxed Cotton Field Jacket",
        price: "165.00",
        currency: "USD",
        in_stock: true,
        url: "https://shop.example/waxed-cotton-field-jacket",
        image: "https://shop.example/img/1311.jpg",
      },
    ],
  });
  assert.strictEqual(items.length, 1);
  assert.strictEqual(items[0].title, "Waxed Cotton Field Jacket");
  assert.strictEqual(items[0].price, "165.00");
  assert.strictEqual(items[0].in_stock, true);
  assert.strictEqual(items[0].url, "https://shop.example/waxed-cotton-field-jacket");
});

test("a javascript: url never reaches an attribute", () => {
  // The merchant typed this field and nothing upstream renders it, so nothing
  // upstream had to make it safe. The server drops it too; this is the second
  // of the two, and it is the one closest to the browser.
  const items = widget.productsForTurn({
    products: [{ id: "x", title: "Trap", url: "javascript:alert(1)" }],
  });
  assert.strictEqual(items[0].url, "", "the card must render without a link");
});

test("a data: image never reaches an attribute", () => {
  const items = widget.productsForTurn({
    products: [
      { id: "x", title: "Trap", image: "data:text/html,<script>alert(1)</script>" },
    ],
  });
  assert.strictEqual(items[0].image, "");
});

test("a product with no title is discarded", () => {
  // A shopper reads an unnamed grey box as a broken site, not a missing field.
  const items = widget.productsForTurn({
    products: [{ id: "x", price: "10.00" }, { id: "y", title: "Real" }],
  });
  assert.deepStrictEqual(items.map((i) => i.title), ["Real"]);
});

test("a turn with no products renders none", () => {
  // CARE, a withheld turn, an escalation, and any reply that recommended
  // nothing all land here — so a client may call this unconditionally.
  assert.deepStrictEqual(widget.productsForTurn({ reply: "hello" }), []);
  assert.deepStrictEqual(widget.productsForTurn({}), []);
  assert.deepStrictEqual(widget.productsForTurn(null), []);
});

test("out of stock is carried, not hidden", () => {
  const items = widget.productsForTurn({
    products: [{ id: "x", title: "Gone", in_stock: false }],
  });
  assert.strictEqual(items[0].in_stock, false);
});

test("markdown emphasis is stripped, not shown", () => {
  // Caught in a screenshot: `compose` writes `**like this**` whether or not
  // anyone asked, and the widget renders with textContent — so the asterisks
  // arrived on screen literally and the panel looked broken.
  const rows = widget.messagesForTurn({
    reply: "The **Waxed Cotton Field Jacket (1311)** is 165.00 USD.",
    ai_disclosure: "You are chatting with an AI assistant.",
  });
  assert.strictEqual(
    rows[0].text,
    "The Waxed Cotton Field Jacket (1311) is 165.00 USD."
  );
});

test("stripping emphasis is not a markdown renderer", () => {
  // It must not grow into one. A link in a reply is a claim about a
  // destination, and destinations belong in a card, where they are checked.
  const kept = "See [our returns page](https://evil.example) and `code`.";
  assert.strictEqual(widget.withoutEmphasis(kept), kept);
});

test("an unpaired asterisk is left alone", () => {
  assert.strictEqual(widget.withoutEmphasis("2 * 3 = 6"), "2 * 3 = 6");
  assert.strictEqual(widget.withoutEmphasis("**"), "**");
});

// ── Paired suggestions in the panel (ADR-0040) ──────────────────────────────
//
// The surface has no model in it on either side, so what is worth testing is
// what the widget *refuses* to show and when it refuses to interrupt.

test("product ids come off the script tag, commas and spaces tolerated", () => {
  // A theme building this attribute in a template loop produces exactly this.
  assert.deepStrictEqual(widget.productIdsFrom(" 1315, 1320, "), ["1315", "1320"]);
});

test("a repeated id is sent once", () => {
  assert.deepStrictEqual(widget.productIdsFrom("1315,1315"), ["1315"]);
});

test("a page with no ids asks for nothing", () => {
  assert.deepStrictEqual(widget.productIdsFrom(""), []);
  assert.deepStrictEqual(widget.productIdsFrom(undefined), []);
});

test("a long page is capped rather than refused", () => {
  const many = Array.from({ length: 40 }, (_, n) => `id_${n}`).join(",");
  assert.strictEqual(widget.productIdsFrom(many).length, 10);
});

test("the config carries the ids and leaves auto-open OFF by default", () => {
  const config = widget.configFrom(
    { dataset: { neuraKey: "fn_pk_x", neuraProducts: "1315" }, src: "https://api.example.com/v1/widget/widget.js" },
    null
  );
  assert.deepStrictEqual(config.productIds, ["1315"]);
  // A panel that opens over the page a shopper is about to pay on is opted
  // into, never inherited.
  assert.strictEqual(config.pairsAutoOpen, false);
});

test("auto-open is on only when the merchant asked for it", () => {
  const config = widget.configFrom(
    { dataset: { neuraKey: "k", neuraProducts: "1315", neuraPairsAutoOpen: "true" }, src: "" },
    { origin: "https://shop.example.com" }
  );
  assert.strictEqual(config.pairsAutoOpen, true);
});

test("no suggestions shows nothing", () => {
  assert.strictEqual(widget.pairsFor({ heading: "Goes well with your Loafer", suggestions: [] }), null);
});

test("suggestions with no heading show nothing", () => {
  // An unattributed "goes well with" names nothing a shopper can judge or
  // reject (ADR-0040 §3).
  assert.strictEqual(widget.pairsFor({ suggestions: [{ id: "1", title: "A boot" }] }), null);
});

test("the heading is the server's words, never composed here", () => {
  const block = widget.pairsFor({
    heading: "Goes well with your Leather Loafer",
    suggestions: [{ id: "1", title: "Suede Desert Boot" }],
  });
  assert.strictEqual(block.heading, "Goes well with your Leather Loafer");
  assert.strictEqual(block.products.length, 1);
});

test("a suggested product with a javascript: url keeps no link", () => {
  const block = widget.pairsFor({
    heading: "Goes well with your Loafer",
    suggestions: [{ id: "1", title: "A boot", url: "javascript:alert(1)" }],
  });
  assert.strictEqual(block.products[0].url, "");
});

test("the panel does not open when there is nothing to show", () => {
  assert.strictEqual(widget.shouldAutoOpenPairs({ pairsAutoOpen: true }, null, false), false);
});

test("the panel does not open when the merchant did not ask", () => {
  assert.strictEqual(
    widget.shouldAutoOpenPairs({ pairsAutoOpen: false }, { heading: "x" }, false),
    false
  );
});

test("the panel opens once, then never again this tab", () => {
  const config = { pairsAutoOpen: true };
  const block = { heading: "Goes well with your Loafer" };
  assert.strictEqual(widget.shouldAutoOpenPairs(config, block, false), true);
  // Once is a suggestion; every visit is nagging.
  assert.strictEqual(widget.shouldAutoOpenPairs(config, block, true), false);
});

// ── What a shopper reads when a message could not be answered (G56) ──────────

test("a network failure reads as one plain sentence, never the browser's own words", () => {
  // What fetch throws when the shopper is offline, or when a refusal is not
  // readable by the page (CORS): the browser's words, in the browser's language.
  for (const err of [new TypeError("Failed to fetch"), new TypeError("Load failed")]) {
    assert.strictEqual(widget.errorTextFor(err), widget.TRANSPORT_ERROR_MESSAGE);
  }
});

test("a server page that is not JSON reads as the same plain sentence", () => {
  const err = new SyntaxError("Unexpected token '<', \"<html><bod\"... is not valid JSON");
  assert.strictEqual(widget.errorTextFor(err), widget.TRANSPORT_ERROR_MESSAGE);
});

test("NEURA's own readable refusal is shown in its own words", () => {
  const err = new Error("A secret key may not be used from a web page.");
  err.fromServer = true;
  assert.strictEqual(widget.errorTextFor(err), "A secret key may not be used from a web page.");
});

test("a refusal with no words of its own, or nothing at all, reads as the plain sentence", () => {
  assert.strictEqual(widget.errorTextFor(new Error("request_failed")), widget.TRANSPORT_ERROR_MESSAGE);
  assert.strictEqual(widget.errorTextFor(undefined), widget.TRANSPORT_ERROR_MESSAGE);
});

// ─── ADR-0057: a signed-in customer's pass, and the Sign in link ─────────────

const PASS = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIzODUifQ.c2ln";

function configWith(dataset) {
  return widget.configFrom(
    { dataset: Object.assign({ neuraKey: "fn_pk_x" }, dataset), src: "https://api.example.com/v1/widget/widget.js" },
    null
  );
}

test("the pass and the sign-in address come off the script tag", () => {
  const config = configWith({
    neuraCustomerPass: PASS,
    neuraSignInUrl: "https://shop.example/account/login",
  });
  assert.strictEqual(config.customerPass, PASS);
  assert.strictEqual(config.signInUrl, "https://shop.example/account/login");
});

test("no pass and no sign-in address is the ordinary chat box", () => {
  const config = configWith({});
  assert.strictEqual(config.customerPass, "");
  assert.strictEqual(config.signInUrl, "");
});

test("a sign-in address that is not a web address is dropped", () => {
  for (const unsafe of ["javascript:alert(1)", "data:text/html,hi", "/account/login", "ftp://x"]) {
    assert.strictEqual(configWith({ neuraSignInUrl: unsafe }).signInUrl, "", unsafe);
  }
});

test("each message carries the pass, never the address", () => {
  const config = configWith({ neuraCustomerPass: PASS });
  assert.deepStrictEqual(widget.messageBody("where is my order?", "cnv_1", config), {
    message: "where is my order?",
    conversation_id: "cnv_1",
    customer_pass: PASS,
  });
  // The socket's address holds the public key only (G34): a pass in an
  // address is written into logs.
  assert.ok(!widget.endpointFor(config.base, config.agent, "stream").includes(PASS));
});

test("a message without a pass says nothing about one", () => {
  const body = widget.messageBody("hi", null, configWith({}));
  assert.deepStrictEqual(body, { message: "hi" });
});

test("the Sign in link shows only when the server asks and the shop gave an address", () => {
  const withUrl = configWith({ neuraSignInUrl: "https://shop.example/login" });
  assert.strictEqual(widget.signInLinkFor({ sign_in: true }, withUrl), "https://shop.example/login");
  assert.strictEqual(widget.signInLinkFor({ sign_in: false }, withUrl), "");
  assert.strictEqual(widget.signInLinkFor({}, withUrl), "");
  // Words only, as the owner decided, when the line has no address.
  assert.strictEqual(widget.signInLinkFor({ sign_in: true }, configWith({})), "");
});

test("a refused pass warns the developer, with the reason and never the pass", () => {
  const warning = widget.passWarningFor({
    customer_pass: "invalid",
    customer_pass_reason: "the signature does not match this shop's customer sign-in secret",
  });
  assert.ok(warning.includes("the signature does not match"));
  assert.ok(warning.includes("customer pass"));
  assert.ok(!warning.includes(PASS));
});

test("a good pass, an expired one, or none warns nobody", () => {
  for (const state of ["valid", "expired", null, undefined]) {
    assert.strictEqual(widget.passWarningFor({ customer_pass: state }), "", String(state));
  }
});

// ── ADR-0062: a handed-over shopper may leave an email ──────────────────────

const ASK = "I can't answer this here. Leave your email so our store can answer you.";
const CONTACT = "Or contact our store: hello@yourshop.example, +94 11 234 5678.";

test("a handover that asks puts the email box between its two lines", () => {
  assert.deepStrictEqual(widget.emailAskFor({ ask_email: true, reply: ASK + "\n" + CONTACT }), {
    before: ASK,
    after: CONTACT,
  });
});

test("with no contact details set there is nothing under the box", () => {
  assert.deepStrictEqual(widget.emailAskFor({ ask_email: true, reply: ASK }), {
    before: ASK,
    after: "",
  });
});

test("the box shows only when the server asks, never from the words", () => {
  for (const payload of [
    { ask_email: false, reply: ASK + "\n" + CONTACT },
    { reply: ASK },
    { ask_email: "true", reply: ASK },
    { ask_email: true, reply: "" },
    null,
    undefined,
  ]) {
    assert.strictEqual(widget.emailAskFor(payload), null);
  }
});

test("an address is checked before it is sent", () => {
  for (const good of ["saman@example.com", "  saman.perera@example.com ", "a+b@shop.co.uk"]) {
    assert.ok(widget.looksLikeEmail(good), good);
  }
  for (const bad of ["", "   ", "saman.perera@", "saman", "@example.com", "saman@example", "a b@c.com", "a@@c.com", null]) {
    assert.ok(!widget.looksLikeEmail(bad), String(bad));
  }
});

test("the address goes to its own route, never into a chat message", () => {
  assert.strictEqual(
    widget.emailEndpointFor("https://api.example", "cnv_01M4"),
    "https://api.example/v1/conversations/cnv_01M4/email"
  );
  assert.strictEqual(
    widget.emailEndpointFor("https://api.example", "a/b?c"),
    "https://api.example/v1/conversations/a%2Fb%3Fc/email"
  );
  // The body is the address and nothing else: no pass, no message.
  assert.deepStrictEqual(JSON.parse(widget.emailBody(" saman@example.com ")), {
    email: "saman@example.com",
  });
});

test("the box's own words, as the owner approved them (R31)", () => {
  assert.strictEqual(widget.EMAIL_LABEL, "Your email");
  assert.strictEqual(widget.EMAIL_SEND, "Send");
  assert.strictEqual(widget.EMAIL_SKIP, "No thanks");
  assert.strictEqual(widget.WRONG_EMAIL_MESSAGE, "Please check your email address.");
});
