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
  assert.strictEqual(config.agent, "care");
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

test("an unknown graph node still produces a status line", () => {
  // Agent #2 will have nodes this file has never heard of, and it must not
  // need a widget change to show progress.
  assert.strictEqual(widget.labelForStep("verify"), "Checking the reply…");
  assert.strictEqual(widget.labelForStep("some_future_node"), widget.STEP_FALLBACK);
  assert.strictEqual(widget.labelForStep(undefined), widget.STEP_FALLBACK);
});
