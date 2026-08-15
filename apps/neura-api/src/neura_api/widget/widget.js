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
 *             data-neura-key="fn_pk_live_..."></script>
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

  var AGENT_DEFAULT = "care";
  var TITLE_DEFAULT = "Chat with us";
  var PLACEHOLDER = "Ask a question…";

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
      return [{ role: "assistant", text: reply, disclosure: disclosure }];
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
    };
  }

  /** `chat` and `stream` URLs for an agent, including the socket scheme swap. */
  function endpointFor(base, agent, kind) {
    var path = base + "/v1/" + encodeURIComponent(agent);
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

      socket.onopen = function () {
        settled = true;
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
        if (!settled) {
          settled = true;
          reject(new Error("socket_closed"));
        } else {
          handlers.onClose();
        }
      };
    });
  };

  StreamTransport.prototype.send = function (message, conversationId) {
    this.socket.send(
      JSON.stringify({
        type: "message",
        content: message,
        conversation_id: conversationId || undefined,
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
    var body = { message: message };
    if (conversationId) {
      body.conversation_id = conversationId;
    }
    return fetch(endpointFor(this.config.base, this.config.agent, "chat"), {
      method: "POST",
      headers: headers,
      body: JSON.stringify(body),
    }).then(function (response) {
      return response.json().then(function (json) {
        if (!response.ok) {
          var detail = (json && json.error && json.error.message) || "";
          throw new Error(detail || "request_failed");
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
      self.config = { key: "", base: "", agent: AGENT_DEFAULT, title: TITLE_DEFAULT, open: false };
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
    };

    NeuraChat.prototype.storageKey = function () {
      return "neura:" + this.config.agent + ":conversation";
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
          self.render({
            role: "error",
            text: (err && err.message) || TRANSPORT_ERROR_MESSAGE,
            disclosure: "",
          });
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
      for (var i = 0; i < rows.length; i += 1) {
        this.render(rows[i]);
      }
      this.setBusy(false);
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
      configFrom: configFrom,
      endpointFor: endpointFor,
      labelForStep: labelForStep,
      messagesForTurn: messagesForTurn,
    };
  }
})();
