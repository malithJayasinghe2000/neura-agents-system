/**
 * NEURA paired suggestions — ADR-0040's fourth surface, client half.
 *
 * Defines <neura-pairs> as a Custom Element with an open Shadow root, for the
 * same reason `widget.js` does: this runs inside an arbitrary merchant's theme,
 * and their CSS must not break our layout nor ours leak into their page.
 *
 * Embedded as two lines on the page that knows what it is displaying:
 *
 *     <script src="https://api.example.com/v1/widget/pairs.js" async></script>
 *     <neura-pairs data-neura-key="fn_pk_live_..."
 *                  data-products="1315,1332"></neura-pairs>
 *
 * Four rules this file exists to keep, each decided in ADR-0040 rather than
 * here:
 *
 *   - **The heading comes from the server and is never composed here.** §3
 *     rules out "Often bought together", "Customers also bought" and
 *     "Trending" — claims about behaviour this system has never observed. A
 *     heading built in the page is a heading a merchant's theme could rewrite,
 *     so `renderInto` uses `data.heading` verbatim or renders nothing at all.
 *   - **Nothing renders when there is nothing good to show.** An empty
 *     `suggestions` array removes the block entirely rather than leaving an
 *     empty bordered box. Showing nothing costs a shopper nothing.
 *   - **`textContent`, never `innerHTML`.** Every string here is a merchant's
 *     own product text, and text placed with `textContent` cannot become code
 *     no matter what it contains. `tools/card.py` makes the same argument from
 *     the server side.
 *   - **`data-products` is a list of product ids and nothing else.** The
 *     surface is never told these came from a cart, because the moment it is,
 *     somebody will want a cart endpoint and that breaks Rule 1.
 *
 * Tested with `node --test` (see tests/widget/pairs.test.js). The tested
 * surface is the pure half — reading config, and deciding what a response
 * renders. Everything below that line is DOM.
 */

(function () {
  "use strict";

  /**
   * How many ids the element will send. The server truncates too
   * (`select.MAX_INPUT_IDS`); this is here so a page with a very long list does
   * not spend the bytes, not as a second opinion about the limit.
   */
  var MAX_IDS = 10;

  /**
   * Read the element's configuration.
   *
   * Ids are split on commas and trimmed, because a theme building this
   * attribute in a template loop produces spaces and trailing separators, and a
   * surface that 400s on `"1315, 1332,"` would be a surface nobody ships.
   */
  function configFrom(element, scriptSrc) {
    var raw = element.getAttribute("data-products") || "";
    var ids = [];
    var seen = {};

    raw.split(",").forEach(function (part) {
      var id = part.trim();
      if (id && !Object.prototype.hasOwnProperty.call(seen, id) && ids.length < MAX_IDS) {
        seen[id] = true;
        ids.push(id);
      }
    });

    return {
      key: element.getAttribute("data-neura-key") || "",
      storeId: element.getAttribute("data-neura-store") || "",
      productIds: ids,
      base: baseFrom(element.getAttribute("data-neura-api") || "", scriptSrc),
    };
  }

  /**
   * Where the API lives.
   *
   * An explicit `data-neura-api` wins; otherwise the origin this script was
   * served from, which is the normal case and needs no configuration at all.
   */
  function baseFrom(explicit, scriptSrc) {
    if (explicit) {
      return explicit.replace(/\/+$/, "");
    }
    if (!scriptSrc) {
      return "";
    }
    return scriptSrc.replace(/\/v1\/widget\/pairs\.js.*$/, "");
  }

  /**
   * What a response renders, or `null` for "remove the block".
   *
   * **The one piece of logic worth testing on its own**, because every way it
   * can be wrong is a claim on a shopper's screen:
   *
   *   - no suggestions → nothing, not an empty box;
   *   - no heading from the server → nothing, because an unattributed "goes
   *     well with" names nothing a shopper can judge or reject (§3);
   *   - a card with no title → dropped, for `tools/card.py`'s reason: a card
   *     with nothing to name reads as a broken site.
   */
  function blockFor(data) {
    if (!data || !data.heading) {
      return null;
    }

    var cards = (data.suggestions || []).filter(function (card) {
      return card && card.id && card.title;
    });

    if (!cards.length) {
      return null;
    }

    return { heading: data.heading, cards: cards };
  }

  /**
   * A price as a shopper reads it, or "" when there is nothing to format.
   *
   * `Intl` where available and a plain join otherwise. Never a guess at a
   * currency: a bare number beside a product is a price claim in whatever
   * currency the shopper assumes, and being wrong about that is the kind of
   * false claim this repository exists to prevent.
   */
  function priceText(card) {
    if (!card.price || !card.currency) {
      return "";
    }
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: card.currency,
      }).format(Number(card.price));
    } catch (err) {
      return card.price + " " + card.currency;
    }
  }

  /**
   * A URL this code may hand to a browser, or "".
   *
   * The server already dropped anything that is not http(s) with a host
   * (`tools/card.py:_safe_url`). This is the same check again on the other side
   * of the wire — not because the server is distrusted, but because this is the
   * only place in the file where a string becomes something a browser resolves,
   * and a second line costs nothing.
   */
  function safeUrl(raw) {
    if (!raw) {
      return "";
    }
    var value = String(raw).trim();
    if (!/^https?:\/\/[^/]/i.test(value)) {
      return "";
    }
    return value;
  }

  var STYLE = [
    ":host{display:block;font-family:inherit;color:inherit}",
    ".neura-pairs{margin:1.5rem 0}",
    ".neura-pairs h2{font-size:1rem;font-weight:600;margin:0 0 .75rem}",
    ".neura-pairs ul{list-style:none;margin:0;padding:0;display:flex;gap:1rem;flex-wrap:wrap}",
    // Capped, not just flexible. Without a ceiling the two cards divide the
    // whole row, and on a desktop cart page that renders a product image several
    // hundred pixels tall — a suggestion block shouting louder than the cart it
    // sits under. Seen on the real storefront, 2026-09-24.
    ".neura-pairs li{flex:0 1 14rem;min-width:0;max-width:14rem}",
    ".neura-pairs a{color:inherit;text-decoration:none;display:block}",
    ".neura-pairs img{width:100%;aspect-ratio:1;object-fit:cover;display:block;border-radius:.25rem}",
    ".neura-pairs .t{margin:.5rem 0 .125rem;font-size:.9375rem;overflow-wrap:anywhere}",
    ".neura-pairs .p{font-size:.875rem;opacity:.8}",
  ].join("");

  /**
   * Render one block into a Shadow root. Replaces whatever was there.
   *
   * Every string arrives through `textContent`. There is no template, no
   * interpolation and no `innerHTML` anywhere below, which is what makes an
   * arbitrary merchant's product title safe to display.
   */
  function renderInto(root, block) {
    root.textContent = "";

    if (!block) {
      return;
    }

    var style = document.createElement("style");
    style.textContent = STYLE;
    root.appendChild(style);

    var section = document.createElement("section");
    section.className = "neura-pairs";

    var heading = document.createElement("h2");
    // The server's words. §3 is enforced by using them rather than by hoping
    // whoever edits this file remembers the rule.
    heading.textContent = block.heading;
    section.appendChild(heading);

    var list = document.createElement("ul");

    block.cards.forEach(function (card) {
      var item = document.createElement("li");
      var url = safeUrl(card.url);
      var target = url ? document.createElement("a") : document.createElement("div");

      if (url) {
        target.setAttribute("href", url);
        // A merchant's own storefront, but the block is injected into a page we
        // do not control, so the link is treated as external.
        target.setAttribute("rel", "noopener");
      }

      var image = safeUrl(card.image);
      if (image) {
        var img = document.createElement("img");
        img.setAttribute("src", image);
        img.setAttribute("loading", "lazy");
        // The title, not "product image": a screen reader reading "product
        // image" three times has been told nothing.
        img.setAttribute("alt", card.title);
        target.appendChild(img);
      }

      var title = document.createElement("div");
      title.className = "t";
      title.textContent = card.title;
      target.appendChild(title);

      var price = priceText(card);
      if (price) {
        var priceEl = document.createElement("div");
        priceEl.className = "p";
        priceEl.textContent = price;
        target.appendChild(priceEl);
      }

      item.appendChild(target);
      list.appendChild(item);
    });

    section.appendChild(list);
    root.appendChild(section);
  }

  /**
   * Ask the server what goes with these products.
   *
   * **Every failure renders nothing.** A network error, a 403 from a
   * misconfigured key, a 500 — none of them is a shopper's problem, and all of
   * them happen on the page where the shopper has already decided to buy. The
   * block is absent rather than apologetic, which is the client half of the
   * server returning an empty 200 (Finding 49's lesson, from the other side).
   */
  function fetchPairing(config) {
    if (!config.key || !config.productIds.length) {
      return Promise.resolve(null);
    }

    var body = { product_ids: config.productIds };
    if (config.storeId) {
      body.store_id = config.storeId;
    }

    return fetch(config.base + "/v1/sell/suggestions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + config.key,
      },
      body: JSON.stringify(body),
    })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(blockFor)
      .catch(function () {
        return null;
      });
  }

  if (typeof document !== "undefined" && typeof window !== "undefined") {
    var SCRIPT_SRC = (document.currentScript && document.currentScript.src) || "";

    var NeuraPairs = function () {
      return Reflect.construct(HTMLElement, [], NeuraPairs);
    };

    NeuraPairs.prototype = Object.create(HTMLElement.prototype);
    NeuraPairs.prototype.constructor = NeuraPairs;
    Object.setPrototypeOf(NeuraPairs, HTMLElement);

    NeuraPairs.prototype.connectedCallback = function () {
      var element = this;
      var root = element.shadowRoot || element.attachShadow({ mode: "open" });

      fetchPairing(configFrom(element, SCRIPT_SRC)).then(function (block) {
        renderInto(root, block);
      });
    };

    if (!window.customElements.get("neura-pairs")) {
      window.customElements.define("neura-pairs", NeuraPairs);
    }
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      MAX_IDS: MAX_IDS,
      baseFrom: baseFrom,
      blockFor: blockFor,
      configFrom: configFrom,
      priceText: priceText,
      safeUrl: safeUrl,
    };
  }
})();
