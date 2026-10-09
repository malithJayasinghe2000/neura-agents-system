/**
 * NEURA chat widget — one file, no dependencies, no build step (ADR-0019).
 *
 * Defines <neura-chat> as a Custom Element with an open Shadow root. The Shadow
 * root is the decisive part rather than a convenience: this code is injected
 * into an arbitrary merchant's theme, and their CSS must not be able to break
 * our layout nor ours leak into their page.
 *
 * Embedded as two lines, which is the whole integration:
 *
 *     <script src="https://api.example.com/v1/widget/widget.js" async
 *             data-neura-key="fn_pk_..."></script>
 *
 * Four rules this file exists to keep, each decided elsewhere:
 *
 *   - `ai_disclosure` renders on EVERY agent message, never only the first
 *     (EU AI Act Art. 50). The server sends it every time for this reason.
 *   - No model-generated text arrives before `verify` has passed (ADR-0016), so
 *     `token` frames are already-verified text and there is nothing to redact
 *     here. The widget never has to decide what is safe to show.
 *   - A withheld reply is rendered as `fallback_message`, and an empty reply
 *     with no fallback is an ERROR, never silence (ADR-0020).
 *   - The key is public and origin-locked (ADR-0014 §3). It identifies the shop
 *     and not the shopper, which is why nothing here ever asserts a customer.
 *
 * Tested with `node --test` (see tests/widget/), which needs no package.json and
 * no install. The tested surface is `messagesForTurn` — the ADR-0020 invariant —
 * plus config and endpoint resolution. Everything below that line is DOM.
 */

(function () {
  "use strict";

  // Empty means "the server chooses" ([ADR-0031]). It used to be "care", so a
  // merchant who wrote no `data-neura-agent` silently got one agent for every
  // message their shoppers ever sent — and a shop paying for two could only
  // ever reach one of them (A13).
  //
  // `data-neura-agent` still works and is still honoured: an integrator who
  // names an agent gets that agent's own route, and a single-agent shop has
  // nothing to dispatch anyway.
  var AGENT_DEFAULT = "";
  var TITLE_DEFAULT = "Chat with us";
  var PLACEHOLDER = "Ask a question…";

  /**
   * Ids accepted from one page. The server truncates too; this is here so a
   * page holding a long list does not spend the bytes.
   */
  var MAX_PAIR_IDS = 10;

  //: Marks that the panel has already opened itself for a suggestion this tab.
  var PAIRS_OPENED_KEY = "neura:pairs:opened";

  /**
   * What the widget says when a turn produced nothing to render.
   *
   * This is the ADR-0020 §4 error path and it must never be reached in normal
   * operation: a withheld turn carries `fallback_message`, and every other
   * state carries a reply. Reaching it means the server sent an empty turn,
   * which is a defect — so this says so plainly rather than apologising in a
   * way a shopper would read as a normal outcome.
   */
  var EMPTY_TURN_MESSAGE =
    "Something went wrong and no answer came back. Please try again.";

  var TRANSPORT_ERROR_MESSAGE =
    "We could not reach the assistant. Please check your connection and try again.";

  /**
   * What a shopper reads when a message could not be answered (G56).
   *
   * Only NEURA's own words, from a refusal the page could read (`fromServer`,
   * set by `RestTransport`), are shown as they are: they were written for a
   * person. Anything else is the browser's or a parser's text ("Failed to
   * fetch", "Unexpected token '<'"), in the browser's language and meaningless
   * to a shopper, so it becomes the one plain sentence above.
   */
  function errorTextFor(err) {
    if (err && err.fromServer && err.message) {
      return err.message;
    }
    return TRANSPORT_ERROR_MESSAGE;
  }

  /**
   * Widget copy for the graph's progress frames.
   *
   * These are OUR words about which node is running, not claims about the
   * shopper's data — a `step` frame names a node and says nothing about the
   * answer, which is exactly why ADR-0016 allows it to be sent before `verify`.
   * An unrecognised node falls through to the generic string, so agent #2
   * needs no change here.
   */
  var STEP_LABELS = {
    guard: "Checking your message…",
    route: "Reading your question…",
    retrieve: "Looking through the shop's information…",
    plan: "Working out what to check…",
    act: "Checking with the shop…",
    triage: "Working…",
    compose: "Writing a reply…",
    verify: "Checking the reply…",
    respond: "Almost there…",
  };
  var STEP_FALLBACK = "Working…";

  // ─── Pure logic. Everything in this section is unit-tested. ────────────────

  /**
   * The rows to render for one completed turn.
   *
   * The single decision point for both transports, deliberately: the REST
   * payload and the socket's `done` frame carry the same fields, so a rule
   * implemented twice would be a rule that eventually differs once.
   *
   * The branch order IS ADR-0020: a reply if there is one, the server's
   * withheld-turn wording if there is not, and an explicit error if there is
   * neither. Note it turns on emptiness rather than on `state === "shadowed"`,
   * so a future state that withholds is covered without touching this file.
   */
  function messagesForTurn(payload) {
    var data = payload || {};
    var reply = data.reply || "";
    var fallback = data.fallback_message || "";
    var disclosure = data.ai_disclosure || "";

    if (reply) {
      return [{ role: "assistant", text: withoutEmphasis(reply), disclosure: disclosure }];
    }
    if (fallback) {
      // The agent did not say this — the merchant's configured wording did, so
      // it is not dressed up as an assistant message. The disclosure still
      // rides along: Article 50 is about the interaction being with a machine,
      // not about any one sentence.
      return [{ role: "system", text: fallback, disclosure: disclosure }];
    }
    // No disclosure on this row: the widget is speaking, not the agent.
    return [{ role: "error", text: EMPTY_TURN_MESSAGE, disclosure: "" }];
  }

  /**
   * Markdown emphasis, as a model writes it and a shopper should not read it.
   *
   * `compose` produces prose for a person, and models write `**like this**`
   * whether or not anyone asked. The widget renders with `textContent`, so the
   * asterisks arrive on screen literally — *"The **Waxed Cotton Field Jacket
   * (1311)** is 165.00 USD"* — which looks like a broken page.
   *
   * **Stripped rather than rendered.** Turning `**` into a `<strong>` means
   * parsing model output into markup, and the one rule this file exists to keep
   * is that nothing off the network becomes markup. Removing the markers is a
   * display fix with no such cost: what is left is the same sentence.
   *
   * Deliberately only the emphasis markers. This is not a markdown renderer and
   * must not grow into one — a link or an image in a reply is a claim about a
   * destination, and destinations belong in a product card, where they are
   * checked.
   */
  function withoutEmphasis(text) {
    return String(text || "")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/__(.+?)__/g, "$1");
  }

  /**
   * Schemes a browser may be handed. [ADR-0030]
   *
   * `javascript:` executes and `data:` can carry a whole document, and both
   * arrive here inside a merchant's own product URL — a field they typed, that
   * nothing upstream renders and therefore nothing upstream had to make safe.
   * The server drops them too; this is the second of the two, because the one
   * that matters is the one closest to the browser.
   */
  var SAFE_URL = /^https?:\/\/[^\s]+$/i;

  /**
   * The products a turn may display, cleaned. [ADR-0030]
   *
   * Pure, and beside `messagesForTurn` for the same reason: it is a decision
   * about what a shopper is shown, so it is testable without a DOM.
   *
   * **Every field is treated as text except the two that are not.** `title`,
   * `price` and the rest are placed with `textContent` later and cannot become
   * markup; `url` and `image` become attributes a browser resolves, so anything
   * that is not plain http(s) is dropped and the card renders without it.
   *
   * A card with no title is discarded outright — a shopper reads an unnamed
   * grey box as a broken site, not as a missing field.
   */
  function productsForTurn(payload) {
    var items = (payload && payload.products) || [];
    var out = [];
    if (!items.length) {
      return out;
    }
    for (var i = 0; i < items.length; i += 1) {
      var item = items[i] || {};
      if (!item.title) {
        continue;
      }
      out.push({
        id: String(item.id || ""),
        title: String(item.title),
        price: item.price ? String(item.price) : "",
        currency: item.currency ? String(item.currency) : "",
        in_stock: item.in_stock === true || item.in_stock === "true",
        url: SAFE_URL.test(String(item.url || "")) ? String(item.url) : "",
        image: SAFE_URL.test(String(item.image || "")) ? String(item.image) : ""
      });
    }
    return out;
  }

  /**
   * The product ids a page handed us, cleaned. [ADR-0040]
   *
   * **The page says what it is displaying; it never says what it means.** These
   * are ids on a page — they are not called a cart here, and must not be,
   * because every platform exposes a cart differently and the moment this
   * knows about carts it stops being portable.
   *
   * Commas and spaces are tolerated: a theme building this attribute in a
   * template loop produces `"1315, 1320,"`, and a widget that ignored a whole
   * page over a trailing comma would be a widget nobody ships.
   */
  function productIdsFrom(raw) {
    var out = [];
    var seen = {};
    String(raw || "").split(",").forEach(function (part) {
      var id = part.trim();
      if (id && !Object.prototype.hasOwnProperty.call(seen, id) && out.length < MAX_PAIR_IDS) {
        seen[id] = true;
        out.push(id);
      }
    });
    return out;
  }

  /**
   * What a suggestions response shows, or `null` for "show nothing".
   *
   * The same three refusals `pairs.js` makes, and for the same reasons: no
   * products means no block; **no heading means no block**, because an
   * unattributed "goes well with" names nothing a shopper can judge; and a card
   * with no title is a grey box a shopper reads as a broken site.
   */
  function pairsFor(payload) {
    if (!payload || !payload.heading) {
      return null;
    }
    var items = productsForTurn({ products: payload.suggestions });
    return items.length ? { heading: String(payload.heading), products: items } : null;
  }

  /**
   * Should the panel open by itself?
   *
   * **Three conditions, and all of them are restrictions.** Opening a chat
   * panel over a page is an interruption, and the cart page is where a shopper
   * has already decided to buy — the one place an interruption can cost the
   * merchant money rather than merely annoy someone.
   *
   *   - the merchant asked for it (`data-neura-pairs-auto-open`), and the
   *     default is **off**: a behaviour this intrusive is opted into, never
   *     inherited;
   *   - there is something worth showing — no suggestion, no interruption;
   *   - it has not already happened this session, so returning to the page
   *     does not reopen it. Once is a suggestion; every time is nagging.
   */
  function shouldAutoOpenPairs(config, block, alreadyOpened) {
    return Boolean(config && config.pairsAutoOpen && block && !alreadyOpened);
  }

  /** Read the embed configuration off the <script> tag that loaded us. */
  function configFrom(script, location) {
    var data = (script && script.dataset) || {};
    var src = (script && script.src) || "";
    var base = data.neuraApi || "";
    if (!base && src) {
      // Default to the origin that served this file — the API hosts it
      // (ADR-0019 §2), so in the common case the merchant configures nothing.
      base = src.replace(/\/v1\/widget\/widget\.js.*$/, "");
    }
    if (!base && location) {
      base = location.origin;
    }
    return {
      key: data.neuraKey || "",
      base: String(base).replace(/\/+$/, ""),
      agent: data.neuraAgent || AGENT_DEFAULT,
      title: data.neuraTitle || TITLE_DEFAULT,
      open: data.neuraOpen === "true",
      // [ADR-0040] on this surface. Absent on every page but the one the
      // merchant chose, which is why the widget asks for suggestions nowhere
      // else and costs nothing on the rest of the storefront.
      productIds: productIdsFrom(data.neuraProducts),
      pairsAutoOpen: data.neuraPairsAutoOpen === "true",
      // ADR-0057: written by the shop's server only for a signed-in customer,
      // and sent with every message. Absent means not signed in.
      customerPass: data.neuraCustomerPass || "",
      // Where the Sign in link goes. Only a plain web address becomes a link.
      signInUrl: SAFE_URL.test(data.neuraSignInUrl || "") ? data.neuraSignInUrl : "",
    };
  }

  /**
   * One message, as both transports send it. [ADR-0057] §4
   *
   * The customer pass travels **in the message, never in an address**: the
   * socket's address is written into logs (G34), and the server checks the
   * pass on every message because a connection outlives a pass.
   */
  function messageBody(message, conversationId, config) {
    var body = { message: message };
    if (conversationId) {
      body.conversation_id = conversationId;
    }
    if (config && config.customerPass) {
      body.customer_pass = config.customerPass;
    }
    return body;
  }

  /**
   * Where the *Sign in* link under a reply goes, or "" for none. [ADR-0057] §7
   *
   * The server says when (`sign_in`), so the widget never guesses from the
   * words; the shop's page says where, and only a checked web address counts.
   */
  function signInLinkFor(payload, config) {
    if (!payload || payload.sign_in !== true || !config) {
      return "";
    }
    return config.signInUrl || "";
  }

  /**
   * The developer's warning for a refused pass, or "". [ADR-0057] §5
   *
   * Only for `invalid`: an expired pass is a page left open, not a mistake.
   * The reason comes from the server, which never repeats the pass in it.
   */
  function passWarningFor(payload) {
    if (!payload || payload.customer_pass !== "invalid") {
      return "";
    }
    var reason = payload.customer_pass_reason || "no reason given";
    return (
      "NEURA: the customer pass in data-neura-customer-pass was refused, so this " +
      "shopper is treated as not signed in: " + reason + "."
    );
  }

  /**
   * `chat` and `stream` URLs, including the socket scheme swap.
   *
   * No agent means the dispatched door — `/v1/chat`, `/v1/stream` — where the
   * server reads the merchant's enabled agents and picks one per message. A
   * named agent keeps its own prefix, unchanged.
   */
  function endpointFor(base, agent, kind) {
    var path = agent ? base + "/v1/" + encodeURIComponent(agent) : base + "/v1";
    if (kind === "stream") {
      return path.replace(/^http/, "ws") + "/stream";
    }
    return path + "/chat";
  }

  function labelForStep(step) {
    return STEP_LABELS[step] || STEP_FALLBACK;
  }

  // ─── Transports. WebSocket first, REST when the socket will not open. ──────

  /**
   * One turn over the socket.
   *
   * The socket buys progress, not earlier text: ADR-0016 means `token` frames
   * carry slices of the already-verified reply, so time to first token is the
   * accepted cost. What the frames prevent is a motionless spinner across a
   * turn that has been measured at tens of seconds — the difference between a
   * system visibly working and one a shopper reads as broken.
   */
  function StreamTransport(config) {
    this.config = config;
    this.socket = null;
  }

  StreamTransport.prototype.connect = function (handlers) {
    var self = this;
    var url =
      endpointFor(this.config.base, this.config.agent, "stream") +
      "?token=" +
      encodeURIComponent(this.config.key);

    return new Promise(function (resolve, reject) {
      var socket;
      try {
        socket = new WebSocket(url);
      } catch (err) {
        reject(err);
        return;
      }
      var settled = false;
      // Whether it ever opened. A socket refused at the handshake fires `error`
      // and then `close`; that `close` is the same refusal, not a dropped chat.
      // Read as one, it drew a second error and threw away the switch to REST
      // the refusal had just made (G56).
      var opened = false;

      socket.onopen = function () {
        settled = true;
        opened = true;
        self.socket = socket;
        resolve(socket);
      };
      socket.onmessage = function (event) {
        var frame;
        try {
          frame = JSON.parse(event.data);
        } catch (err) {
          return;
        }
        handlers.onFrame(frame);
      };
      socket.onerror = function () {
        // Before `open` this is "the socket would not connect" and the caller
        // falls back to REST. After it, the turn in flight is lost and the
        // shopper is told — a dropped socket must not look like a slow answer.
        if (!settled) {
          settled = true;
          reject(new Error("socket_failed"));
        }
      };
      socket.onclose = function () {
        self.socket = null;
        if (!opened) {
          if (!settled) {
            settled = true;
            reject(new Error("socket_closed"));
          }
          return;
        }
        handlers.onClose();
      };
    });
  };

  StreamTransport.prototype.send = function (message, conversationId) {
    var body = messageBody(message, conversationId, this.config);
    this.socket.send(
      JSON.stringify({
        type: "message",
        content: body.message,
        conversation_id: body.conversation_id,
        customer_pass: body.customer_pass,
      })
    );
  };

  StreamTransport.prototype.close = function () {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  };

  /**
   * One turn over REST.
   *
   * The fallback path, and the only one that carries `Idempotency-Key` — the
   * socket has no equivalent, which ADR-0019 §4 records as the accepted cost of
   * preferring it.
   */
  function RestTransport(config) {
    this.config = config;
  }

  RestTransport.prototype.send = function (message, conversationId) {
    var headers = {
      "Content-Type": "application/json",
      Authorization: "Bearer " + this.config.key,
    };
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      headers["Idempotency-Key"] = crypto.randomUUID();
    }
    var body = messageBody(message, conversationId, this.config);
    return fetch(endpointFor(this.config.base, this.config.agent, "chat"), {
      method: "POST",
      headers: headers,
      body: JSON.stringify(body),
    }).then(function (response) {
      return response.json().then(function (json) {
        if (!response.ok) {
          var detail = (json && json.error && json.error.message) || "";
          var refused = new Error(detail || "request_failed");
          // NEURA's own sentence, written for a person: the only error text a
          // shopper is ever shown as it is (`errorTextFor`).
          refused.fromServer = Boolean(detail);
          throw refused;
        }
        return (json && json.data) || {};
      });
    });
  };

  // ─── The element ───────────────────────────────────────────────────────────

  var STYLES = [
    ":host{all:initial;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;",
    "position:fixed;right:20px;bottom:20px;z-index:2147483000;}",
    "*{box-sizing:border-box;}",
    ".launcher{width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;",
    "background:#1b2333;color:#fff;font-size:22px;line-height:1;box-shadow:0 6px 24px rgba(0,0,0,.24);}",
    ".launcher:focus-visible{outline:3px solid #7aa2ff;outline-offset:2px;}",
    ".panel{display:none;flex-direction:column;width:360px;max-width:calc(100vw - 40px);",
    "height:520px;max-height:calc(100vh - 40px);background:#fff;color:#1b2333;",
    "border-radius:14px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.28);}",
    ".panel[data-open='true']{display:flex;}",
    ".head{display:flex;align-items:center;justify-content:space-between;gap:8px;",
    "padding:12px 14px;background:#1b2333;color:#fff;}",
    ".title{font-size:15px;font-weight:600;}",
    ".head button{background:transparent;border:0;color:#fff;font-size:20px;cursor:pointer;line-height:1;}",
    ".disclosure{padding:6px 14px;background:#eef1f6;color:#4a5468;font-size:11px;}",
    ".log{flex:1;overflow-y:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px;}",
    ".row{display:flex;flex-direction:column;gap:3px;max-width:88%;}",
    ".row[data-role='shopper']{align-self:flex-end;align-items:flex-end;}",
    ".bubble{padding:9px 12px;border-radius:12px;font-size:14px;line-height:1.45;white-space:pre-wrap;",
    "word-wrap:break-word;overflow-wrap:anywhere;}",
    "[data-role='shopper'] .bubble{background:#1b2333;color:#fff;border-bottom-right-radius:4px;}",
    "[data-role='assistant'] .bubble{background:#f1f3f8;border-bottom-left-radius:4px;}",
    "[data-role='system'] .bubble{background:#fff8e6;border:1px solid #f0dfae;color:#6b5726;}",
    "[data-role='error'] .bubble{background:#fdecec;border:1px solid #f2c3c3;color:#8c2b2b;}",
    ".note{font-size:10.5px;color:#79839a;}",
    ".signin{align-self:flex-start;margin-top:4px;padding:7px 14px;border-radius:9px;background:#1b2333;",
    "color:#fff;font-size:13px;font-weight:600;text-decoration:none;}",
    ".signin:hover{background:#2c3850;}",
    ".signin:focus-visible{outline:2px solid #7aa2ff;outline-offset:1px;}",
    // Product cards ([ADR-0030]). A stacked list of wide rows rather than a
    // strip of tall tiles: a chat panel is ~340px, most merchants publish no
    // image at all (the test shop publishes none for any product), and a tile
    // built around a picture looks broken exactly when there is not one. A row
    // reads the same with or without.
    //
    // `flex:0 0 auto` because `.log` is a flex column — without it the strip is
    // a shrinkable item and the last line of the last card is clipped, which is
    // what shipped first and what a screenshot caught.
    ".cards{display:flex;flex-direction:column;gap:6px;flex:0 0 auto;}",
    ".card{display:flex;align-items:center;gap:9px;padding:8px;border:1px solid #e6e9f0;",
    "border-radius:10px;background:#fff;text-decoration:none;color:inherit;}",
    "a.card:hover{border-color:#b9c4dc;background:#fafbfd;}",
    "a.card:focus-visible{outline:2px solid #7aa2ff;outline-offset:1px;}",
    ".card-thumb{flex:0 0 46px;width:46px;height:46px;border-radius:7px;background:#eef1f6;",
    "object-fit:cover;display:block;}",
    ".card-body{display:flex;flex-direction:column;gap:2px;min-width:0;}",
    ".card-title{font-size:13px;line-height:1.3;font-weight:600;}",
    ".card-meta{font-size:11.5px;color:#5b6478;}",
    ".card-stock{color:#3f7a4a;}",
    ".card-stock[data-stock='false']{color:#8c2b2b;}",
    ".status{font-size:12px;color:#79839a;font-style:italic;min-height:16px;padding:0 14px 4px;}",
    ".compose{display:flex;gap:8px;padding:10px 12px;border-top:1px solid #e6e9f0;}",
    ".compose input{flex:1;padding:9px 11px;border:1px solid #d3d8e3;border-radius:9px;font-size:14px;",
    "font-family:inherit;color:inherit;background:#fff;}",
    ".compose input:focus-visible{outline:2px solid #7aa2ff;outline-offset:0;}",
    ".compose button{padding:9px 14px;border:0;border-radius:9px;background:#1b2333;color:#fff;",
    "font-size:14px;cursor:pointer;}",
    ".compose button[disabled]{opacity:.5;cursor:default;}",
    "@media (prefers-reduced-motion:no-preference){.status{transition:opacity .2s;}}",
  ].join("");

  function applyStyles(root) {
    // Constructable stylesheets are not subject to a page's `style-src` CSP,
    // where an injected <style> element is. That matters here because the CSP
    // in question is the MERCHANT's, and a widget that forces them to add
    // 'unsafe-inline' is a widget asking a third party to weaken their own
    // security on our behalf. The <style> path is only for browsers too old to
    // have the modern one.
    if (typeof CSSStyleSheet !== "undefined" && "adoptedStyleSheets" in Document.prototype) {
      try {
        var sheet = new CSSStyleSheet();
        sheet.replaceSync(STYLES);
        root.adoptedStyleSheets = [sheet];
        return;
      } catch (err) {
        /* fall through */
      }
    }
    var style = document.createElement("style");
    style.textContent = STYLES;
    root.appendChild(style);
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      // textContent, never innerHTML. Everything rendered here came off the
      // network — a shopper's own words echoed back, a merchant's policy text,
      // a model's reply — and none of it is markup we authored.
      node.textContent = text;
    }
    return node;
  }

  /**
   * Build the element class.
   *
   * A function rather than a value because it touches `HTMLElement` at
   * definition time, and this file is required by `node --test` to reach the
   * pure functions above. Nothing here runs outside a browser.
   */
  function defineChatElement() {
    function NeuraChat() {
      var self = Reflect.construct(HTMLElement, [], NeuraChat);
      self.config = {
        key: "",
        base: "",
        agent: AGENT_DEFAULT,
        title: TITLE_DEFAULT,
        open: false,
        productIds: [],
        pairsAutoOpen: false
      };
      self.conversationId = null;
      self.transport = null;
      self.pending = false;
      self.provisional = null;
      return self;
    }

    NeuraChat.prototype = Object.create(HTMLElement.prototype);
    NeuraChat.prototype.constructor = NeuraChat;
    Object.setPrototypeOf(NeuraChat, HTMLElement);

    NeuraChat.prototype.configure = function (config) {
      this.config = config;
      return this;
    };

    NeuraChat.prototype.connectedCallback = function () {
      var self = this;
      var root = this.attachShadow({ mode: "open" });
      applyStyles(root);

      // Per tab, not per browser: a conversation can contain order details, and
      // localStorage would resume a stranger's chat on a shared computer.
      try {
        this.conversationId = sessionStorage.getItem(this.storageKey()) || null;
      } catch (err) {
        this.conversationId = null;
      }

      this.launcher = element("button", "launcher", "💬");
      this.launcher.setAttribute("aria-label", this.config.title);
      this.launcher.addEventListener("click", function () {
        self.toggle();
      });

      this.panel = element("div", "panel");
      this.panel.setAttribute("role", "dialog");
      this.panel.setAttribute("aria-label", this.config.title);

      var head = element("div", "head");
      head.appendChild(element("div", "title", this.config.title));
      var close = element("button", "", "×");
      close.setAttribute("aria-label", "Close chat");
      close.addEventListener("click", function () {
        self.toggle(false);
      });
      head.appendChild(close);

      // A standing disclosure in addition to the per-message one. Art. 50 is
      // about the person knowing, and a shopper who scrolled up should not have
      // to scroll back down to find out what they are talking to.
      this.disclosure = element("div", "disclosure", "You are chatting with an AI assistant.");

      this.log = element("div", "log");
      this.log.setAttribute("role", "log");
      this.log.setAttribute("aria-live", "polite");
      this.status = element("div", "status", "");

      var compose = element("form", "compose");
      this.input = element("input");
      this.input.setAttribute("placeholder", PLACEHOLDER);
      this.input.setAttribute("aria-label", PLACEHOLDER);
      this.input.setAttribute("maxlength", "4000");
      this.send = element("button", "", "Send");
      this.send.setAttribute("type", "submit");
      compose.appendChild(this.input);
      compose.appendChild(this.send);
      compose.addEventListener("submit", function (event) {
        event.preventDefault();
        self.submit();
      });

      this.panel.appendChild(head);
      this.panel.appendChild(this.disclosure);
      this.panel.appendChild(this.log);
      this.panel.appendChild(this.status);
      this.panel.appendChild(compose);
      root.appendChild(this.panel);
      root.appendChild(this.launcher);

      if (this.config.open) {
        this.toggle(true);
      }

      // Last, and only when a page handed over ids. Everything above must be
      // built before a network reply can arrive, or a fast response renders
      // into a panel that does not exist yet.
      if (this.config.productIds.length) {
        this.loadPairs();
      }
    };

    /**
     * Ask what goes with the products this page named. [ADR-0040]
     *
     * **No model of ours runs in this**, on either side: the endpoint chooses
     * by the merchant's own product text, and nothing here generates a
     * sentence. What arrives is a fixed heading and a list of products, so
     * there is no prose for a false claim to live in — which is the property
     * that lets this render without a `verify` step in front of it.
     *
     * **Every failure is silent.** A network error, a key without
     * `sell:suggest:read`, a shop that cannot search — none of them is a
     * shopper's problem, and all of them happen on a page where the shopper is
     * about to pay. Nothing renders and the panel does not open.
     */
    NeuraChat.prototype.loadPairs = function () {
      var self = this;

      fetch(this.config.base + "/v1/sell/suggestions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + this.config.key
        },
        body: JSON.stringify({ product_ids: this.config.productIds })
      })
        .then(function (response) {
          return response.ok ? response.json() : null;
        })
        .then(function (payload) {
          var block = pairsFor(payload);
          if (!block) {
            return;
          }
          self.renderPairs(block);
          if (shouldAutoOpenPairs(self.config, block, self.pairsAlreadyOpened())) {
            self.rememberPairsOpened();
            self.toggle(true);
          }
        })
        .catch(function () {
          /* silent: see above */
        });
    };

    /**
     * The suggestion, in the log, and **not dressed as something the assistant
     * said**.
     *
     * It gets the `note` style rather than an assistant bubble because no
     * assistant wrote it. A fixed heading rendered as a reply would be the
     * widget putting words in the agent's mouth — harmless today, and exactly
     * the habit that makes a later generated line indistinguishable from a
     * fixed one.
     */
    NeuraChat.prototype.renderPairs = function (block) {
      var row = element("div", "row");
      row.dataset.role = "assistant";
      row.appendChild(element("div", "note", block.heading));
      this.log.appendChild(row);
      this.renderProducts(block.products);
    };

    /**
     * Once per tab. Returning to the cart page must not reopen the panel — one
     * suggestion is help, and the same suggestion on every visit is nagging.
     *
     * `sessionStorage`, like the conversation id and for the same reason: a
     * shared computer must not carry this between people.
     */
    NeuraChat.prototype.pairsAlreadyOpened = function () {
      try {
        return sessionStorage.getItem(PAIRS_OPENED_KEY) === "true";
      } catch (err) {
        // A browser refusing storage gets the cautious answer: treat it as
        // already opened, so the failure mode is a panel that stays shut
        // rather than one that opens on every page view.
        return true;
      }
    };

    NeuraChat.prototype.rememberPairsOpened = function () {
      try {
        sessionStorage.setItem(PAIRS_OPENED_KEY, "true");
      } catch (err) {
        /* storage refused; the panel opens this once and that is acceptable */
      }
    };

    NeuraChat.prototype.storageKey = function () {
      // A dispatched widget stores under its own name rather than under the
      // empty string. The key is per-agent on purpose — a shop that switches a
      // page from one agent to another starts a new conversation rather than
      // resuming one the other service never had.
      return "neura:" + (this.config.agent || "dispatch") + ":conversation";
    };

    NeuraChat.prototype.toggle = function (force) {
      var open = force === undefined ? this.panel.dataset.open !== "true" : force;
      this.panel.dataset.open = open ? "true" : "false";
      this.launcher.style.display = open ? "none" : "";
      if (open) {
        this.input.focus();
      }
    };

    NeuraChat.prototype.render = function (row) {
      var node = element("div", "row");
      node.dataset.role = row.role;
      node.appendChild(element("div", "bubble", row.text));
      if (row.disclosure) {
        node.appendChild(element("div", "note", row.disclosure));
      }
      this.log.appendChild(node);
      this.log.scrollTop = this.log.scrollHeight;
      return node;
    };

    NeuraChat.prototype.setStatus = function (text) {
      this.status.textContent = text || "";
    };

    NeuraChat.prototype.setBusy = function (busy) {
      this.pending = busy;
      this.send.disabled = busy;
      this.input.disabled = busy;
      if (!busy) {
        this.setStatus("");
        this.input.focus();
      }
    };

    NeuraChat.prototype.submit = function () {
      var message = (this.input.value || "").trim();
      if (!message || this.pending) {
        return;
      }
      this.input.value = "";
      this.render({ role: "shopper", text: message, disclosure: "" });
      this.setBusy(true);
      this.setStatus(STEP_FALLBACK);
      this.deliver(message);
    };

    /** Try the socket; fall back to REST for the rest of the session. */
    NeuraChat.prototype.deliver = function (message) {
      var self = this;
      if (this.transport instanceof RestTransport) {
        this.viaRest(message);
        return;
      }
      if (this.transport && this.transport.socket) {
        this.transport.send(message, this.conversationId);
        return;
      }
      var stream = new StreamTransport(this.config);
      stream
        .connect({
          onFrame: function (frame) {
            self.onFrame(frame);
          },
          onClose: function () {
            // Closed mid-turn: the answer is not coming, and saying so beats a
            // spinner that never resolves.
            if (self.pending) {
              self.render({ role: "error", text: TRANSPORT_ERROR_MESSAGE, disclosure: "" });
              self.setBusy(false);
            }
            self.transport = null;
          },
        })
        .then(function () {
          self.transport = stream;
          stream.send(message, self.conversationId);
        })
        .catch(function () {
          // The socket would not open — a corporate proxy, a blocked upgrade.
          // REST for the rest of the session rather than a retry per turn.
          self.transport = new RestTransport(self.config);
          self.viaRest(message);
        });
    };

    NeuraChat.prototype.viaRest = function (message) {
      var self = this;
      this.transport.send(message, this.conversationId).then(
        function (data) {
          self.complete(data);
        },
        function (err) {
          self.render({ role: "error", text: errorTextFor(err), disclosure: "" });
          self.setBusy(false);
        }
      );
    };

    NeuraChat.prototype.onFrame = function (frame) {
      switch (frame.type) {
        case "accepted":
          this.remember(frame.conversation_id);
          break;
        case "step":
          // `name` is the node, and it is all the frame carries — the socket
          // deliberately adds nothing to what the runner reported.
          this.setStatus(labelForStep(frame.name));
          break;
        case "tool_call":
          this.setStatus(STEP_LABELS.act);
          break;
        case "token":
          // Already-verified text (ADR-0016), so it can go straight to the
          // screen. It is provisional only in the sense that `done` carries the
          // authoritative payload and replaces it.
          if (!this.provisional) {
            this.setStatus("");
            this.provisional = this.render({ role: "assistant", text: "", disclosure: "" });
          }
          this.provisional.firstChild.textContent += frame.content || "";
          this.log.scrollTop = this.log.scrollHeight;
          break;
        case "done":
          this.complete(frame);
          break;
        case "error":
          this.render({
            role: "error",
            text: (frame.error && frame.error.message) || TRANSPORT_ERROR_MESSAGE,
            disclosure: "",
          });
          this.setBusy(false);
          break;
        default:
          break;
      }
    };

    /**
     * One turn is over. Both transports land here, and `messagesForTurn` is the
     * only thing that decides what is shown — including the case where nothing
     * came back at all, which must be visible rather than silent (ADR-0020).
     */
    NeuraChat.prototype.complete = function (payload) {
      if (this.provisional) {
        // Drop the streamed text and re-render from the payload, so the streamed
        // and non-streamed paths cannot disagree about what a turn displayed.
        this.provisional.remove();
        this.provisional = null;
      }
      this.remember(payload.conversation_id);
      if (payload.ai_disclosure) {
        this.disclosure.textContent = payload.ai_disclosure;
      }
      var rows = messagesForTurn(payload);
      var last = null;
      for (var i = 0; i < rows.length; i += 1) {
        last = this.render(rows[i]);
      }
      var signIn = signInLinkFor(payload, this.config);
      if (signIn && last) {
        last.appendChild(this.signInLink(signIn));
      }
      var warning = passWarningFor(payload);
      if (warning && !this.warnedAboutPass && typeof console !== "undefined") {
        // Once per page: the developer needs to see it, the console does not
        // need it on every message.
        this.warnedAboutPass = true;
        console.warn(warning);
      }
      this.renderProducts(productsForTurn(payload));
      this.setBusy(false);
    };

    /**
     * The *Sign in* link. [ADR-0057] §7, Q5
     *
     * The widget owns the tag and the words; the one value from outside, the
     * address, was checked against `SAFE_URL` in `configFrom`. The shop's own
     * sign-in page, so it opens in the same tab, where the shopper comes back
     * signed in.
     */
    NeuraChat.prototype.signInLink = function (url) {
      var link = element("a", "signin", "Sign in");
      link.href = url;
      return link;
    };

    /**
     * The cards, under the reply that named them. [ADR-0030]
     *
     * **The widget owns every tag and every attribute here.** Nothing from the
     * network is ever written as markup: text goes in through `element()`,
     * which uses `textContent`, and the only two values that reach an attribute
     * were checked against `SAFE_URL` first.
     *
     * A card links out to the merchant's own product page, in a new tab, with
     * `rel="noopener noreferrer"` so the page it opens cannot reach back into
     * the tab it was opened from.
     */
    NeuraChat.prototype.renderProducts = function (items) {
      if (!items.length) {
        return;
      }
      var strip = element("div", "cards");
      for (var i = 0; i < items.length; i += 1) {
        strip.appendChild(this.card(items[i]));
      }
      this.log.appendChild(strip);
      this.log.scrollTop = this.log.scrollHeight;
    };

    NeuraChat.prototype.card = function (item) {
      // An anchor when there is somewhere to go, a plain box when there is not.
      // A card that looks clickable and is not is worse than one that does not.
      var node = document.createElement(item.url ? "a" : "div");
      node.className = "card";
      if (item.url) {
        node.href = item.url;
        node.target = "_blank";
        node.rel = "noopener noreferrer";
      }

      // A thumbnail when the merchant published one, an empty tile of the same
      // size when they did not — so a card with no image is a card, not a
      // shorter card with a gap where a picture should be.
      if (item.image) {
        var image = document.createElement("img");
        image.className = "card-thumb";
        image.src = item.image;
        // The title, not "product image" — a shopper using a screen reader gets
        // the same information a sighted one does.
        image.alt = item.title;
        image.loading = "lazy";
        node.appendChild(image);
      } else {
        node.appendChild(element("div", "card-thumb"));
      }

      var body = element("div", "card-body");
      body.appendChild(element("div", "card-title", item.title));

      // Price and availability on one line. Two stacked lines of small grey
      // text beside a 46px thumbnail is taller than the thumbnail and reads as
      // a list of fields rather than as a product.
      var meta = element("div", "card-meta");
      var price = (item.price + " " + item.currency).trim();
      if (price) {
        meta.appendChild(element("span", "", price));
        meta.appendChild(element("span", "", " · "));
      }
      var stock = element("span", "card-stock", item.in_stock ? "In stock" : "Out of stock");
      stock.dataset.stock = item.in_stock ? "true" : "false";
      meta.appendChild(stock);
      body.appendChild(meta);

      node.appendChild(body);
      return node;
    };

    NeuraChat.prototype.remember = function (conversationId) {
      if (!conversationId || conversationId === this.conversationId) {
        return;
      }
      this.conversationId = conversationId;
      try {
        sessionStorage.setItem(this.storageKey(), conversationId);
      } catch (err) {
        /* private browsing — continuity is lost, the chat still works */
      }
    };

    return NeuraChat;
  }

  // ─── Bootstrap ─────────────────────────────────────────────────────────────

  function boot() {
    var script = document.currentScript;
    if (!script) {
      var all = document.querySelectorAll("script[data-neura-key]");
      script = all[all.length - 1];
    }
    var config = configFrom(script, window.location);
    if (!config.key) {
      // Loud, and only in the console: a merchant who mis-pasted the snippet
      // needs to know, and a shopper must never see our integration errors.
      console.error("[neura] data-neura-key is missing — the widget will not start.");
      return;
    }
    if (!customElements.get("neura-chat")) {
      customElements.define("neura-chat", defineChatElement());
    }
    var mount = function () {
      if (document.querySelector("neura-chat")) {
        return;
      }
      var node = document.createElement("neura-chat");
      node.configure(config);
      document.body.appendChild(node);
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mount);
    } else {
      mount();
    }
  }

  // The browser half runs only in a browser, so `node --test` can require this
  // file for the pure functions above without a DOM.
  if (typeof document !== "undefined" && typeof window !== "undefined") {
    boot();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      EMPTY_TURN_MESSAGE: EMPTY_TURN_MESSAGE,
      STEP_FALLBACK: STEP_FALLBACK,
      TRANSPORT_ERROR_MESSAGE: TRANSPORT_ERROR_MESSAGE,
      configFrom: configFrom,
      endpointFor: endpointFor,
      errorTextFor: errorTextFor,
      labelForStep: labelForStep,
      messageBody: messageBody,
      messagesForTurn: messagesForTurn,
      pairsFor: pairsFor,
      passWarningFor: passWarningFor,
      productIdsFrom: productIdsFrom,
      productsForTurn: productsForTurn,
      shouldAutoOpenPairs: shouldAutoOpenPairs,
      signInLinkFor: signInLinkFor,
      withoutEmphasis: withoutEmphasis,
    };
  }
})();
