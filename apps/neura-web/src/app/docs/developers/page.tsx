import type { Metadata } from "next";
import Link from "next/link";
import { NEURA_HOST, OPENAPI_HREF } from "@/lib/site";

/**
 * Guide for developers — canvas board 25, approved by the owner 2026-09-30.
 *
 * Built from the board, with what is true in the code where the board marked
 * something as undecided (ADR-0051 §4). Since ADR-0052 the shop owner makes the
 * shop token and runs the check in their dashboard; a developer cannot run the
 * check alone (G10). FiveNeurals still makes the chat box key. Only the OpenAPI
 * file is published: the written specification names commerce platforms
 * (Rule 1).
 */
export const metadata: Metadata = {
  title: "Guide for developers",
  description:
    "Connect a shop to NEURA: build the bridge, say what your shop can do, check your work, connect, and add the chat box.",
};

/**
 * The addresses, in the order a developer should build them. A first-time
 * developer does not know the assistants' names, so this is by what each address
 * gives, not by assistant (A1 review, CONNECTING_A_NEW_SHOP_LOG.md). A missing
 * address never breaks an assistant: it cannot do that one thing and hands those
 * questions to the shop's team.
 */
const TIERS: { title: string; note: string; rows: [string, string][] }[] = [
  {
    title: "Start with these three",
    note: "Enough to connect. The assistant can find products and talk about them.",
    rows: [
      ["GET /health", "What your shop can do (step 2)"],
      ["GET /products", "A page of products, and search"],
      ["GET /products/{id}", "One product"],
    ],
  },
  {
    title: "Add these for better answers",
    note: "Each one you add, the assistant can do one more thing.",
    rows: [
      ["GET /inventory", "Stock: whether something can be bought now"],
      ["GET /policies", "Returns, shipping and warranty pages"],
      ["GET /categories", "Your categories: what you do sell when nothing fits"],
    ],
  },
  {
    title: "Only for order questions",
    note: "For a shop that wants the assistant to look up orders.",
    rows: [
      ["GET /orders", "A page of orders, and search by email or order number"],
      ["GET /orders/{id}", "One order"],
      ["GET /customers/{id}", "One customer, never a member of staff"],
    ],
  },
];

/**
 * Every setting the chat box reads from its line (`configFrom` in widget.js),
 * the two the old table missed included (G28).
 */
const ATTRIBUTES: [string, React.ReactNode][] = [
  ["data-neura-key", "The chat box key. Required"],
  [
    "data-neura-title",
    <>
      The panel&apos;s heading. Default <em>Chat with us</em>
    </>,
  ],
  [
    "data-neura-open",
    <>
      <code>true</code> opens the panel when the page loads
    </>,
  ],
  [
    "data-neura-agent",
    <>
      Usually leave it out: NEURA picks the right assistant for each question.{" "}
      <code>care</code> (questions about the shop) or <code>sell</code> (help choosing) sends
      every question on the page to that one
    </>,
  ],
  [
    "data-neura-api",
    <>
      Only if you serve <code>widget.js</code> from somewhere else: NEURA&apos;s address. By
      default, the address the file came from
    </>,
  ],
  ["data-neura-products", "The products a page shows, for suggestions. See below"],
  [
    "data-neura-pairs-auto-open",
    <>
      <code>true</code> lets a suggestion open the panel. See below
    </>,
  ],
];

/**
 * The five steps at a glance — and who does each one.
 *
 * "The shop owner" (here, CHECK_STEPS and CONNECT_STEPS) is true only while a
 * developer has no dashboard account. When the developer role (D3) is built and
 * a developer can press Check and Connect, these say "You" (the owner's decision,
 * CONNECTING_A_NEW_SHOP_LOG.md).
 */
const STEPS: [string, string, string][] = [
  ["1", "Build the bridge", "You"],
  ["2", "Say what your shop can do", "You"],
  ["3", "Check your work", "You and the shop owner"],
  ["4", "Connect your shop", "The shop owner"],
  ["5", "Add the chat box", "You and FiveNeurals"],
];

const ON_THIS_PAGE: [string, string][] = [
  ["overview", "Overview"],
  ["start", "Before you start"],
  ["build", "1 · Build the bridge"],
  ["health", "2 · Say what your shop can do"],
  ["check", "3 · Check your work"],
  ["connect", "4 · Connect your shop"],
  ["chat", "5 · Add the chat box"],
  ["views", "Optional: product views"],
  ["changes", "Change messages"],
  ["trouble", "If something doesn't work"],
  ["reference", "The full specification"],
];

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="flex scroll-mt-6 flex-col gap-4">
      <h2 className="m-0 text-[22px] font-semibold tracking-[-0.01em] md:text-[26px]">{title}</h2>
      {children}
    </section>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="m-0 text-base leading-[1.6] text-body">{children}</p>;
}

function Pre({ children }: { children: React.ReactNode }) {
  return (
    <pre className="m-0 overflow-x-auto rounded-xl bg-ink px-[18px] py-4 font-mono text-[13px] leading-[1.65] text-[#f5f5f5]">
      {children}
    </pre>
  );
}

function Table({ head, rows }: { head: [string, string]; rows: [string, React.ReactNode][] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full border-collapse text-left text-[15px]">
        <thead className="bg-[#fafafa]">
          <tr>
            {head.map((h, i) => (
              <th
                key={h}
                scope="col"
                className={`px-3 py-2.5 text-[13px] font-medium text-quiet ${i === 0 ? "md:w-[300px]" : ""}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, what], i) => (
            <tr key={name} className={i < rows.length - 1 ? "border-b border-[#efefef]" : ""}>
              <td className="px-3 py-2.5 align-top whitespace-nowrap">
                <code className="font-mono text-[0.92em]">{name}</code>
              </td>
              <td className="px-3 py-2.5 align-top text-body">{what}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Rules({ items, ordered }: { items: React.ReactNode[]; ordered?: boolean }) {
  const List = ordered ? "ol" : "ul";
  return (
    <List
      className={`m-0 flex flex-col gap-2 pl-5 text-[15px] ${ordered ? "list-decimal" : "list-disc"} leading-[1.55] text-body`}
    >
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </List>
  );
}

/**
 * Names and what each means: step 5's settings, product views' fields. A list
 * rather than a table: on a phone the long names would squeeze the
 * explanations to a few words per line.
 */
function Defs({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="m-0 overflow-hidden rounded-xl border border-line text-[15px]">
      {items.map(([name, what], i) => (
        <div
          key={name}
          className={`grid gap-1 px-4 py-3 md:grid-cols-[260px_minmax(0,1fr)] md:gap-4 ${i < items.length - 1 ? "border-b border-[#efefef]" : ""}`}
        >
          <dt>
            <code className="font-mono text-[0.92em]">{name}</code>
          </dt>
          <dd className="m-0 leading-[1.5] text-body">{what}</dd>
        </div>
      ))}
    </dl>
  );
}

const b = (text: string) => <strong className="font-semibold text-ink">{text}</strong>;
const c = (text: string) => <code className="font-mono text-[0.92em]">{text}</code>;
const note = (text: React.ReactNode) => (
  <span className="mt-0.5 block text-[14px] leading-[1.5] text-quiet">{text}</span>
);

/**
 * The four fields of /health. The exact values are the part a developer gets
 * wrong (G14): NEURA reads any `status` but "ok" as a shop that is down
 * (wire.py parse_health, stores.py _negotiate), and the check tool fails a
 * missing `spec_version` (http_checks.py).
 */
const HEALTH_FIELDS: [string, React.ReactNode][] = [
  [
    "status",
    <>
      Exactly {c('"ok"')}.
      {note(<>Anything else, even {c('"healthy"')}, and NEURA treats your shop as down.</>)}
    </>,
  ],
  [
    "spec_version",
    <>
      {c('"1.0"')}, the version of this format.
      {note("The check tool fails without it.")}
    </>,
  ],
  ["platform", "Your shop system's name, in any words. For information only."],
  ["capabilities", "What your bridge can do: the table below."],
];

/**
 * What to write in `capabilities`, starting from what the developer built: they
 * think "I built this, what do I write?" (the owner's A2 review). In step 1's
 * groups, so group 1 shows all three addresses, /health included, which is the
 * list itself and has no word. Each word is checked against the tools'
 * `requires=` and the generic adapter (CONNECTING_A_NEW_SHOP_LOG.md, A2).
 * Change messages get no word yet: NEURA has no address that receives them (G13).
 * A no-break space keeps "GET" with its path on a phone.
 */
const CAPABILITY_GROUPS: {
  title: string;
  rows: { built: React.ReactNode; word: React.ReactNode }[];
}[] = [
  {
    title: "1. Start with these three",
    rows: [
      {
        built: c("GET\u00a0/health"),
        word: <>nothing{note("This address is the list itself.")}</>,
      },
      {
        built: (
          <>
            {c("GET\u00a0/products")}
            <br />
            {c("GET\u00a0/products/{id}")}
          </>
        ),
        word: c("product.read"),
      },
      { built: <>Search: {c("GET\u00a0/products?q=…")}</>, word: c("product.search") },
    ],
  },
  {
    title: "2. Add these for better answers",
    rows: [
      { built: c("GET\u00a0/inventory?variant_ids=…"), word: c("inventory.read") },
      { built: c("GET\u00a0/policies"), word: c("policy.read") },
      { built: c("GET\u00a0/categories"), word: c("category.read") },
    ],
  },
  {
    title: "3. Only for order questions",
    rows: [
      { built: c("GET\u00a0/orders/{id}"), word: c("order.read") },
      {
        built: (
          <>
            Search: {c("GET\u00a0/orders?email=…")}
            {note(
              <>
                Also by {c("phone")}, {c("customer_id")} and {c("order_number")}.
              </>,
            )}
          </>
        ),
        word: c("order.search"),
      },
      { built: c("GET\u00a0/customers/{id}"), word: c("customer.read") },
    ],
  },
  {
    title: "Extras",
    rows: [
      {
        built: (
          <>
            {c("GET\u00a0/products?updated_since=…")}
            {note("Returns only what changed since then.")}
          </>
        ),
        word: (
          <>
            {c("sync.incremental")}
            {note("Optional. Without it, NEURA reads every product each time.")}
          </>
        ),
      },
      {
        built: <>Change messages{note("Your shop tells NEURA when something changes.")}</>,
        word: (
          <>
            nothing yet
            {note(<>NEURA can&apos;t receive them yet. Leave out {c("events.realtime")}.</>)}
          </>
        ),
      },
    ],
  },
];

function CapabilityTable() {
  return (
    <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full border-collapse text-left text-[15px]">
        <thead className="bg-[#fafafa]">
          <tr>
            <th scope="col" className="px-3 py-2.5 text-[13px] font-medium text-quiet md:w-[300px]">
              You built
            </th>
            <th scope="col" className="px-3 py-2.5 text-[13px] font-medium text-quiet">
              Write this word
            </th>
          </tr>
        </thead>
        {CAPABILITY_GROUPS.map((group) => (
          <tbody key={group.title} className="border-t border-line">
            <tr>
              <th
                scope="colgroup"
                colSpan={2}
                className="px-3 pt-3.5 pb-1.5 text-[13px] font-semibold text-ink"
              >
                {group.title}
              </th>
            </tr>
            {group.rows.map((row, i) => (
              <tr key={i} className="border-t border-[#efefef]">
                <td className="px-3 py-2.5 align-top text-body">{row.built}</td>
                <td className="px-3 py-2.5 align-top text-body">{row.word}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

type WhoStep = { title: React.ReactNode; who: string; note: React.ReactNode };

/** A few steps in order, each saying who does it: steps 3 and 4. */
function WhoSteps({ steps }: { steps: WhoStep[] }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-0 overflow-hidden rounded-xl border border-line p-0">
      {steps.map((step, i) => (
        <li
          key={i}
          className={`flex gap-3 px-4 py-3.5 ${i < steps.length - 1 ? "border-b border-[#efefef]" : ""}`}
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-[1.5px] border-ink text-[13px] font-semibold">
            {i + 1}
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex items-start justify-between gap-3">
              <span className="min-w-0 text-[15px] font-medium text-ink">{step.title}</span>
              <span className="shrink-0 rounded-full bg-[#f0f0f0] px-2.5 py-0.5 text-[13px] text-body">
                {step.who}
              </span>
            </div>
            <span className="text-[15px] leading-[1.5] text-body">{step.note}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}

/**
 * Step 3 as it happens since ADR-0052: the shop owner makes the token and runs
 * the check in their dashboard; a developer cannot run it alone (G10). The
 * address must be public and `https://` (G47, addresses.py), is never followed
 * through a redirect (GenericClient), and is the one that gets connected, which
 * nothing can change afterwards (G52).
 */
const CHECK_STEPS: WhoStep[] = [
  {
    title: "The shop owner sends you the shop token",
    who: "Shop owner",
    note: (
      <>
        They make it in their NEURA dashboard. Put it in your bridge&apos;s setting, in place of
        your test text.
      </>
    ),
  },
  {
    title: "Put your bridge online",
    who: "You",
    note: (
      <>
        At an {c("https://")} address on the public internet. NEURA won&apos;t call{" "}
        {c("localhost")}, a private network or plain {c("http://")}.
      </>
    ),
  },
  {
    title: "Send the shop owner the bridge's address",
    who: "You",
    note: (
      <>
        The exact address on your live shop, for example{" "}
        {c("https://yourshop.example/neura/v1")}. NEURA doesn&apos;t follow redirects. The address
        that passes is the one that gets connected, and it can&apos;t be changed afterwards.
      </>
    ),
  },
  {
    title: "The shop owner presses Check",
    who: "Shop owner",
    note: (
      <>
        If something is wrong, they send you the full check. Fix what it names, then ask them to
        check again.
      </>
    ),
  },
];

/**
 * Real output of the dashboard's check (`developer_text` in
 * neura_api/jobs/shop_check.py), shortened: a bridge that accepts any token and
 * whose search ignores the words. Problems come first.
 */
const FULL_CHECK_EXAMPLE = `NEURA check · https://yourshop.example/neura/v1 · 2026-10-01 09:30 UTC

✘ auth.rejects_wrong_token     /orders accepted an invalid bearer token (HTTP 200)
    → The token is being ignored rather than verified.
⚠ products.search_no_match     search returned results for nonsense text
    → Over-broad matching floods the agent's context with irrelevant products.
✔ health                       ok
✔ products.get_missing         ok
…
18 passed · 1 failed · 1 warning(s)`;

/**
 * What a clean check cannot see (G18): whether the answers are true. Each line
 * is something a shopper would otherwise be told wrong. A draft is kept from
 * shoppers everywhere NEURA shows products (G37).
 */
const BY_HAND: React.ReactNode[] = [
  <>
    {b("Stock.")} A sold-out product says {c('"in_stock": false')}.
  </>,
  <>
    {b("Prices.")} The same as on the shop&apos;s page, with the currency as three capital
    letters, such as {c("EUR")}.
  </>,
  <>
    {b("Hidden products.")} One the shop doesn&apos;t show yet comes as{" "}
    {c('"status": "draft"')}. The assistant never mentions a draft.
  </>,
  <>
    {b("Customers.")} If you built {c("/customers/{id}")}, a member of staff&apos;s id answers{" "}
    {c("404")}.
  </>,
];

/**
 * Step 4 since ADR-0052 §5: the shop owner connects, after a clean check of the
 * same address. Connect saves the address and the token NEURA made, then queues
 * a full copy (console_connect.py). The copy keeps products, categories and
 * policy pages only (SYNCED_TYPES in neura_commerce/sync/engine.py); the
 * assistants' tools ask the bridge live. A new token stops NEURA sending the old
 * one at once, but the bridge accepts the old one until it is changed (G49).
 */
const CONNECT_STEPS: WhoStep[] = [
  {
    title: "The shop owner presses Connect",
    who: "Shop owner",
    note: (
      <>
        In their dashboard: <em>Connect and copy my catalogue</em>. It works only after a check
        with no problems.
      </>
    ),
  },
  {
    title: "NEURA copies the shop's catalogue",
    who: "NEURA",
    note: (
      <>
        Your products, page by page, and your categories and policy pages if you built them.
        Orders and customers are not copied.
      </>
    ),
  },
  {
    title: (
      <>
        The owner sees <em>Your shop is connected</em>
      </>
    ),
    who: "Shop owner",
    note: (
      <>
        Then <em>Your catalogue is copied</em>, with the number of products.
      </>
    ),
  },
];

const AFTER_CONNECT: React.ReactNode[] = [
  <>
    {b("Keep the bridge online, at the same address.")} The assistant asks it questions live
    while shoppers chat: searches, products, stock.
  </>,
  <>
    {b("Keep the shop token secret.")} Never in a web page, the browser or a public code
    repository. NEURA can&apos;t show it again, not even to the shop owner: if it&apos;s lost,
    the owner makes a new one.
  </>,
  <>
    {b("A new token from the owner? Put it in straight away.")} Until you do, the assistant
    can&apos;t read the shop, and the old token still works for whoever has it. Then ask the
    owner to press <em>Check again</em>.
  </>,
];

/**
 * Step 5. FiveNeurals still makes the chat box key (`make key-new … PUBLIC=1
 * ORIGINS=…`). A public key holds a list of exact addresses (`allowed_origins`),
 * so one key covers the live shop, www. and a test site (G32, corrected).
 * Shopper pages only (G25).
 */
const CHAT_STEPS: WhoStep[] = [
  {
    title: "Send FiveNeurals the shop's web addresses",
    who: "You",
    note: (
      <>
        Every exact address the chat box will run on, for example{" "}
        {c("https://yourshop.example")} and {c("https://www.yourshop.example")}, and a test site
        if you have one. One key can cover them all.
      </>
    ),
  },
  {
    title: "FiveNeurals makes the chat box key",
    who: "FiveNeurals",
    note: (
      <>
        A public key that starts with {c("fn_pk_")}. It works only from the addresses you sent.
      </>
    ),
  },
  {
    title: "Add the line to every page shoppers see",
    who: "You",
    note: (
      <>
        Not your admin pages: staff questions would use AI and mix with real shoppers&apos;
        chats.
      </>
    ),
  },
];

/**
 * The line's rules. A secret key in a page is refused with a sentence the chat
 * box shows (`SECRET_KEY_IN_PAGE`, G55). The live connection is a `wss://` socket on NEURA's
 * address, and styles are constructable stylesheets, which a page's
 * `style-src` does not block (widget.js).
 */
const CHAT_RULES: React.ReactNode[] = [
  <>
    {b("The key is public, and that's fine.")} It works only from the addresses it was made
    for. {c("www.")} and no {c("www.")}, {c("http")} and {c("https")}, are different addresses.
  </>,
  <>
    {b("Never put a secret key in a page.")} Secret keys start with {c("fn_sk_")}, and anyone
    can read a page&apos;s source. NEURA refuses one there, and the chat box says why.
  </>,
  <>
    {b("Keep the key in the shop's settings,")} like the shop token, not in the template. A new
    key then needs no code change.
  </>,
  <>
    {b("It won't break your page.")} One file, no dependencies, loaded {c("async")}. It draws
    itself in its own box, so your styles don&apos;t reach it.
  </>,
  <>
    {b("Strict content security policy?")} Allow our address in {c("script-src")}, and in{" "}
    {c("connect-src")} with both {c("https://")} and {c("wss://")}. No {c("unsafe-inline")}{" "}
    needed.
  </>,
];

/**
 * How a developer sees it work. The dashboard tick is the key's
 * `last_used_at`, set by any request with it; a page load makes none. The
 * practice-mode note is `WIDGET_WITHHELD_MESSAGE`. A wrong address is
 * `ORIGIN_NOT_ALLOWED`, which the page may not read (middleware/cors.py), so
 * the chat box can only say it could not reach the assistant (seen in a real
 * browser; G56 is the browser's own "Failed to fetch" beside it).
 */
const CHAT_WORKS: React.ReactNode[] = [
  <>Open a shop page: the chat button appears at the bottom right.</>,
  <>
    Send one test message (it uses AI). The shop owner&apos;s dashboard then shows{" "}
    <em>The chat box is on your shop</em>.
  </>,
  <>
    In practice mode, every reply is a short <em>your message has been received</em> note. The
    owner reads the real reply in Review.
  </>,
  <>
    Every message gets <em>We could not reach the assistant</em>? The page&apos;s address is
    probably not on the key: check {c("www.")}, {c("http")} or {c("https")}, and the test site.
  </>,
];

/**
 * Suggestions (ADR-0040, in the chat panel since ADR-0041). The ids are the
 * bridge's `external_id`s, at most 10 (`MAX_PAIR_IDS`, G26). A product with no
 * stored pairing queues one model job in the background and the shopper gets
 * the word path's answer now (ADR-0045, pairing/cache.py; G27). Every failure
 * is silent by design (`loadPairs`).
 */
const PAIRS_RULES: React.ReactNode[] = [
  <>
    {b("The ids your bridge sends")} (each product&apos;s {c("external_id")}), separated by
    commas. At most 10 count.
  </>,
  <>
    {b("Only on the page that shows them,")} usually the basket. The line normally lives in a
    shared layout: let that page hand the layout its ids, and leave the setting out everywhere
    else.
  </>,
  <>
    {b("This uses AI.")} The first time a product appears here, NEURA asks an AI model once, in
    the background, what goes with it, and keeps the answer. The shopper never waits.
  </>,
  <>
    {b("Want the panel to open by itself?")} Add {c('data-neura-pairs-auto-open="true"')}. It
    opens at most once per visit, and only when there is a suggestion. Off by default.
  </>,
  <>
    {b("Nothing shows?")} Failures here are silent on purpose: the shopper is about to pay. Look
    at the {c("suggestions")} request in your browser&apos;s Network tab, and ask the shop owner
    whether their shop has suggestions.
  </>,
];

/**
 * Optional: product views (ADR-0044, ADR-0048, ADR-0049). Part of NEURA-SELL:
 * the dashboard lists Sold out only for a shop with it (shop-sidebar.tsx). The
 * switch lives in the shop and governs sending, NEURA has none (0044 §3); the
 * shoppers' consent is the shop's (0044 §5); the key needs an agreement on
 * record (ApiKeyRepository.issue). Every answer below was seen on the live API
 * (CONNECTING_A_NEW_SHOP_LOG.md, G58 to G64). The owner's decision: optional,
 * and said to be part of NEURA-SELL (G63).
 */
const VIEW_STEPS: WhoStep[] = [
  {
    title: "The shop owner decides, and signs a data agreement",
    who: "Shop owner",
    note: <>With FiveNeurals. Without it, NEURA stores nothing about shoppers.</>,
  },
  {
    title: "FiveNeurals makes your secret key",
    who: "FiveNeurals",
    note: (
      <>
        It starts with {c("fn_sk_")} and is made for sending product views. It can only be made
        once the agreement is recorded.
      </>
    ),
  },
  {
    title: "Build a setting, off by default, and the sending",
    who: "You",
    note: (
      <>
        While the setting is off, your server sends nothing. NEURA has no switch of its own:
        what it receives, it keeps.
      </>
    ),
  },
  {
    title: "The shop owner turns the setting on",
    who: "Shop owner",
    note: (
      <>
        Once the shop asks its shoppers for permission. The agreement makes that the shop&apos;s
        job, so ask the shop owner how it is done.
      </>
    ),
  },
];

/** `ObservedEvent` in neura_core/observation/models.py, one row per field. */
const VIEW_FIELDS: [string, React.ReactNode][] = [
  [
    "event_id",
    <>
      Your own id for this event, 16 to 64 characters. Send the same one again and it counts
      once, so a retry is safe
    </>,
  ],
  [
    "session_id",
    <>
      One per shopper visit, 16 to 128 characters, so the list counts visits and not only views.
      Never the shop&apos;s session cookie itself: make it from the session with a secret only
      your server holds (a keyed hash)
    </>,
  ],
  [
    "type",
    <>
      <code>product.viewed</code> when a shopper opens a product page. <code>cart.added</code>{" "}
      when a product goes into the basket, once the add worked
    </>,
  ],
  [
    "product_id",
    <>
      The product&apos;s <code>external_id</code>, the same id your bridge sends
    </>,
  ],
  [
    "occurred_at",
    <>
      When it happened, with a time zone. Not older than 7 days, and not more than 5 minutes
      ahead
    </>,
  ],
  [
    "in_stock",
    <>
      Views only: could the product be bought at that moment (at least one variant in stock),{" "}
      <code>true</code> or <code>false</code>. Leave it out of <code>cart.added</code>
    </>,
  ],
];

const VIEW_RULES: React.ReactNode[] = [
  <>
    {b("From your server only.")} Never from the shop&apos;s pages: anyone can read a page, and
    NEURA refuses a secret key sent from one.
  </>,
  <>{b("Nothing about who the shopper is.")} No name, email, IP address or browser details.</>,
  <>{b("Never slow a page down.")} Send in the background, for example from a queue.</>,
  <>
    {b("Kept for 7 days, then deleted.")} If the agreement ends, everything is deleted at once.
  </>,
];

const VIEW_WORKS: React.ReactNode[] = [
  <>
    Each event is answered {c("202")} with {c('"stored": true')}. The same {c("event_id")} again
    is answered {c('"stored": false')}: it was already counted.
  </>,
  <>A wrong or extra field is answered {c("400")}, and the error names the field.</>,
  <>
    {c("403")} with {c("DPA_REQUIRED")}: the agreement isn&apos;t recorded yet. Ask the shop owner.
  </>,
];

export default function DeveloperGuide() {
  return (
    <div className="flex gap-12 px-4 pt-7 pb-12 md:px-14 md:pt-12 md:pb-16">
      <aside className="hidden w-[220px] shrink-0 lg:block">
        <nav aria-label="On this page" className="sticky top-8 flex flex-col gap-0.5">
          <span className="px-3 pb-2 text-xs font-medium text-quiet">On this page</span>
          {ON_THIS_PAGE.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className="flex h-9 items-center rounded-lg px-3 text-sm text-body no-underline hover:bg-[#f0f0f0]"
            >
              {label}
            </a>
          ))}
        </nav>
      </aside>

      <div className="flex max-w-[820px] min-w-0 flex-1 flex-col gap-12">
        <section id="overview" className="flex flex-col gap-5">
          <p className="m-0 text-[13px] font-medium text-quiet">For developers</p>
          <h1 className="m-0 text-[30px] leading-[1.15] font-semibold tracking-[-0.02em] md:text-[40px]">
            Connect a shop to NEURA
          </h1>
          <P>
            NEURA&apos;s assistants answer shoppers from the shop&apos;s own data. You do two
            things: build a small {b("bridge")} so NEURA can read the shop, and add {b("one line")}{" "}
            to the shop&apos;s pages for the chat box. Any shop can connect, including one you built
            yourself.
          </P>
          <div className="flex flex-col gap-2 rounded-xl border border-line px-[18px] py-4">
            <span className="text-[15px] font-semibold">NEURA only reads</span>
            <span className="text-[15px] leading-[1.5] text-body">
              It never changes anything in the shop: no orders, no prices, no stock. Every address
              you build is a {c("GET")}.
            </span>
          </div>
          <ol className="m-0 flex list-none flex-col gap-0 overflow-hidden rounded-xl border border-line p-0">
            {STEPS.map(([n, step, who], i) => (
              <li
                key={n}
                className={`flex items-center gap-3 px-4 py-3 ${i < STEPS.length - 1 ? "border-b border-[#efefef]" : ""}`}
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-[13px] font-semibold text-white">
                  {n}
                </span>
                <a
                  href={`#${["build", "health", "check", "connect", "chat"][i]}`}
                  className="flex-1 text-[15px] font-medium text-ink no-underline hover:underline"
                >
                  {step}
                </a>
                <span className="shrink-0 rounded-full bg-[#f0f0f0] px-2.5 py-0.5 text-[13px] text-body">
                  {who}
                </span>
              </li>
            ))}
          </ol>
        </section>

        <Section id="start" title="Before you start">
          <div className="flex flex-col gap-2 rounded-xl bg-[#f5f5f5] px-[18px] py-4">
            <span className="text-[15px] font-semibold">Download the OpenAPI file</span>
            <span className="text-[15px] leading-[1.5] text-body">
              It describes every address and every field. Keep it open while you build, or point a
              code generator at it.
            </span>
            <a
              href={OPENAPI_HREF}
              download
              className="mt-1 flex h-10 w-fit items-center rounded-lg bg-ink px-4 text-[14px] font-medium text-white no-underline"
            >
              Download the OpenAPI file
            </a>
          </div>
        </Section>

        <Section id="build" title="1 · Build the bridge">
          <P>
            First ask FiveNeurals whether a ready-made bridge exists for the shop&apos;s system. If
            it does, install it like any other add-on and go to step 2. If not, build the addresses
            below. Put them under any prefix, usually {c("/neura/v1")}.
          </P>
          <div className="flex flex-col gap-4">
            {TIERS.map((tier, n) => (
              <div key={tier.title} className="flex flex-col gap-2">
                <span className="text-[15px] font-semibold">
                  {n + 1}. {tier.title}
                </span>
                <span className="text-[15px] leading-[1.5] text-body">{tier.note}</span>
                <Table head={["Address", "Gives the assistant"]} rows={tier.rows} />
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-1 rounded-xl border border-line px-[18px] py-4">
            <span className="text-[15px] font-semibold">Not sure what the shop needs?</span>
            <span className="text-[15px] leading-[1.5] text-body">
              Build the first three, connect, and add the rest later. Nothing breaks: what the
              assistant can&apos;t answer, it hands to the shop&apos;s team.
            </span>
          </div>
          <Rules
            items={[
              <>{b("Everything is GET.")} No address changes anything in the shop.</>,
              <>
                {b("Check the shop token on every address except")} {c("/health")}. NEURA sends{" "}
                {c("Authorization: Bearer <shop token>")}; refuse a request without it. Read the
                token from a setting, for example {c("NEURA_SHOP_TOKEN")}, never from code. The
                shop owner makes the real token in their NEURA dashboard and sends it to you; until
                then, put any text in that setting to test.
              </>,
              <>
                {b("Pages by cursor, not page number.")} Return an opaque {c("next_cursor")}; NEURA
                sends it back unchanged.
              </>,
              <>{b("The exact format")} of every answer is in the OpenAPI file you downloaded.</>,
            ]}
          />
        </Section>

        <Section id="health" title="2 · Say what your shop can do">
          <P>
            {c("/health")} tells NEURA what your bridge can do. The assistant gets only what is on
            this list, so it is the one answer to get exactly right.
          </P>
          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium text-quiet">
              Example: a bridge with groups 1 and 2 from step 1
            </span>
            <Pre>{`{
  "status": "ok",
  "spec_version": "1.0",
  "platform": "yourshop",
  "capabilities": [
    "product.read",
    "product.search",
    "inventory.read",
    "policy.read",
    "category.read"
  ]
}`}</Pre>
          </div>
          <Table head={["Field", "What to write"]} rows={HEALTH_FIELDS} />
          <div className="flex flex-col gap-2">
            <span className="text-[15px] font-semibold">What to list</span>
            <span className="text-[15px] leading-[1.5] text-body">
              Find each address you built in step 1, and write its word in the list.
            </span>
          </div>
          <CapabilityTable />
          <div className="grid gap-3 md:grid-cols-2">
            <div className="flex flex-col gap-1 rounded-xl border border-line px-[18px] py-4">
              <span className="flex items-center gap-2 text-[15px] font-semibold">
                <span
                  aria-hidden
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#f0f0f0] text-[13px]"
                >
                  ✓
                </span>
                Leave one out: that&apos;s safe
              </span>
              <span className="text-[15px] leading-[1.5] text-body">
                The assistant isn&apos;t given that job, so it never tries it. Build it later, add
                it to the list, and NEURA sees the change within a minute. Nothing to reconnect.
              </span>
            </div>
            <div className="flex flex-col gap-1 rounded-xl border border-ink px-[18px] py-4">
              <span className="flex items-center gap-2 text-[15px] font-semibold">
                <span
                  aria-hidden
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[13px] text-white"
                >
                  ✗
                </span>
                List one you didn&apos;t build: it fails quietly
              </span>
              <span className="text-[15px] leading-[1.5] text-body">
                NEURA reads a missing address as <em>nothing there</em>. List {c("product.search")}{" "}
                while your search still finds nothing, and the assistant tells shoppers you
                don&apos;t sell things you do. The check tool in step 3 can&apos;t tell either.
              </span>
            </div>
          </div>
          <P>
            {b("No token on this one.")} {c("/health")} is the only address anyone may open, so you
            can check your bridge from a browser. Put no shop data in it.
          </P>
        </Section>

        <Section id="check" title="3 · Check your work">
          <P>
            The shop owner runs the check from their NEURA dashboard, as often as you need. There is
            no tool to download. It asks your bridge about 20 questions, the way the assistant will,
            and names anything wrong. Every question is a {c("GET")}, so nothing in the shop
            changes.
          </P>
          <WhoSteps steps={CHECK_STEPS} />
          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium text-quiet">
              Example: the full check the shop owner sends you (shortened)
            </span>
            <Pre>{FULL_CHECK_EXAMPLE}</Pre>
          </div>
          <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[15px] leading-[1.55] text-body">
            <li className="flex gap-3">
              <span className="w-4 shrink-0 text-center font-semibold text-ink">✘</span>
              <span>
                {b("A problem.")} The shop owner can&apos;t connect while there is one.
              </span>
            </li>
            <li className="flex gap-3">
              <span className="w-4 shrink-0 text-center font-semibold text-ink">⚠</span>
              <span>
                {b("A warning.")} It doesn&apos;t stop the owner connecting, but each one means a
                worse answer for a shopper. Fix it anyway.
              </span>
            </li>
          </ul>
          <div className="flex flex-col gap-2 rounded-xl border border-line px-[18px] py-4">
            <span className="text-[15px] font-semibold">
              The check proves the format, not the facts
            </span>
            <span className="text-[15px] leading-[1.5] text-body">
              A clean check means your answers have the right shape, not that they are true. Compare
              a few products in the shop with what your bridge sends:
            </span>
            <Rules items={BY_HAND} />
          </div>
        </Section>

        <Section id="connect" title="4 · Connect your shop">
          <P>
            You have nothing to press here. The shop owner connects the shop in their dashboard, and
            NEURA reads it for the first time.
          </P>
          <WhoSteps steps={CONNECT_STEPS} />
          <div className="flex flex-col gap-2 rounded-xl border border-line px-[18px] py-4">
            <span className="text-[15px] font-semibold">Your part after connecting</span>
            <Rules items={AFTER_CONNECT} />
          </div>
        </Section>

        <Section id="chat" title="5 · Add the chat box">
          <P>One line of HTML puts the chat box on the shop&apos;s pages.</P>
          <WhoSteps steps={CHAT_STEPS} />
          <Pre>{`<script src="https://${NEURA_HOST}/v1/widget/widget.js" async
        data-neura-key="fn_pk_…"></script>`}</Pre>
          <Rules items={CHAT_RULES} />
          <div className="flex flex-col gap-2 rounded-xl border border-line px-[18px] py-4">
            <span className="text-[15px] font-semibold">How you&apos;ll know it works</span>
            <Rules items={CHAT_WORKS} />
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-[15px] font-semibold">Settings</span>
            <span className="text-[15px] leading-[1.5] text-body">
              Each one is an attribute on the same line.
            </span>
          </div>
          <Defs items={ATTRIBUTES} />
          <div className="flex flex-col gap-3 rounded-xl border border-line px-[18px] py-4">
            <span className="text-[15px] font-semibold">
              Optional: suggestions on the basket page
            </span>
            <span className="text-[15px] leading-[1.5] text-body">
              Tell the chat box which products a page shows, and it suggests what goes with them, in
              the chat panel.
            </span>
            <Pre>{`<script src="https://${NEURA_HOST}/v1/widget/widget.js" async
        data-neura-key="fn_pk_…"
        data-neura-products="1042,1077"></script>`}</Pre>
            <Rules items={PAIRS_RULES} />
          </div>
        </Section>

        <Section
          id="views"
          title={
            <>
              Optional: product views{" "}
              <span className="font-normal text-quiet">(part of NEURA-SELL)</span>
            </>
          }
        >
          <P>
            NEURA-SELL can show the shop owner a {b("Sold out list")}: sold-out products that
            shoppers kept opening in the last 7 days.{" "}
            <Link
              href="/sell/#sold-out"
              className="font-medium text-ink underline underline-offset-2"
            >
              See what the owner sees
            </Link>
          </P>
          <P>
            For it, your shop&apos;s server tells NEURA each time a shopper opens a product or adds
            one to the basket. Build it only if the shop owner wants it.
          </P>
          <WhoSteps steps={VIEW_STEPS} />
          <span className="text-[15px] font-semibold">One request per event</span>
          <Pre>{`POST https://${NEURA_HOST}/v1/observe/events
Authorization: Bearer fn_sk_…
Content-Type: application/json

{
  "event_id": "ev_7f3a9c2e1b4d4e8a",
  "session_id": "s_2c9e41b7d05f4a63",
  "type": "product.viewed",
  "product_id": "1042",
  "occurred_at": "2026-10-01T09:30:00Z",
  "in_stock": false
}`}</Pre>
          <Defs items={VIEW_FIELDS} />
          <P>Ids use only letters, digits, {c("-")} and {c("_")}. Any other field is refused.</P>
          <Rules items={VIEW_RULES} />
          <div className="flex flex-col gap-2 rounded-xl border border-line px-[18px] py-4">
            <span className="text-[15px] font-semibold">How you&apos;ll know it works</span>
            <Rules items={VIEW_WORKS} />
          </div>
        </Section>

        <Section id="changes" title="Change messages">
          <P>
            Your bridge may tell NEURA when a product or order changes.{" "}
            {b("NEURA does not use these yet.")} Until it does, the shop owner presses{" "}
            <em>Sync now</em> in their dashboard after adding products or changing stock.
          </P>
        </Section>

        <Section id="trouble" title="If something doesn't work">
          <dl className="m-0 overflow-hidden rounded-[14px] border border-line text-[15px]">
            {[
              [
                <>{c("/health")} answers, everything else fails</>,
                <>
                  Usually your bridge&apos;s database settings. A {c("/health")} that doesn&apos;t
                  touch the database stays green while every other address fails.
                </>,
              ],
              [
                "Every request is refused",
                "The shop token in your bridge's settings is empty or different from the one FiveNeurals holds.",
              ],
              [
                "The chat box doesn't appear",
                "The line isn't on the page, or your shop is still using a cached copy of its settings.",
              ],
              [
                "The chat box appears but is refused",
                <>
                  The key was made for a different address: {c("www.")}, or {c("http")} versus{" "}
                  {c("https")}.
                </>,
              ],
              [
                "Product views never arrive",
                "The switch is off, the key is a public one, or nothing on your server is sending the queued events.",
              ],
            ].map(([seen, fix], i, all) => (
              <div
                key={i}
                className={`grid gap-1 px-4 py-3.5 md:grid-cols-[280px_minmax(0,1fr)] md:gap-4 md:px-5 ${i < all.length - 1 ? "border-b border-[#efefef]" : ""}`}
              >
                <dt className="font-medium">{seen}</dt>
                <dd className="m-0 leading-[1.5] text-body">{fix}</dd>
              </div>
            ))}
          </dl>
        </Section>

        <section
          id="reference"
          className="flex scroll-mt-6 flex-col gap-4 rounded-2xl border border-line p-5 md:flex-row md:items-center md:justify-between md:p-6"
        >
          <div className="flex flex-col gap-1">
            <span className="text-lg font-semibold">The full specification</span>
            <span className="text-[15px] leading-[1.5] text-body">
              Every field of every address. Where this page and the specification disagree, the
              specification is right.
            </span>
          </div>
          <a
            href={OPENAPI_HREF}
            download
            className="flex h-11 shrink-0 items-center justify-center rounded-xl bg-ink px-5 text-[15px] font-medium text-white no-underline"
          >
            Download the OpenAPI file
          </a>
        </section>
      </div>
    </div>
  );
}
