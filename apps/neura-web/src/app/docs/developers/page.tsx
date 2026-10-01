import type { Metadata } from "next";
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
      ["GET /health", "What your shop can do — step 2"],
      ["GET /products", "A page of products, and search"],
      ["GET /products/{id}", "One product"],
    ],
  },
  {
    title: "Add these for better answers",
    note: "Each one you add, the assistant can do one more thing.",
    rows: [
      ["GET /inventory", "Stock — whether something can be bought now"],
      ["GET /policies", "Returns, shipping and warranty pages"],
      ["GET /categories", "Your categories — what you do sell when nothing fits"],
    ],
  },
  {
    title: "Only for order questions",
    note: "For a shop that wants the assistant to look up orders.",
    rows: [
      ["GET /orders", "A page of orders, and search by email or order number"],
      ["GET /orders/{id}", "One order"],
      ["GET /customers/{id}", "One customer — never a member of staff"],
    ],
  },
];

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
      <code>true</code> starts with the panel open
    </>,
  ],
  [
    "data-neura-products",
    "NEURA-SELL: the product ids on a basket page, so the panel can suggest what goes with them",
  ],
  [
    "data-neura-agent",
    "Only to pin a page to one assistant. Leave it out and NEURA picks the right one per question",
  ],
];

/** The five steps at a glance — and who does each one. */
const STEPS: [string, string, string][] = [
  ["1", "Build the bridge", "You"],
  ["2", "Say what your shop can do", "You"],
  ["3", "Check your work", "You and the shop owner"],
  ["4", "Connect your shop", "FiveNeurals"],
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

/**
 * Step 3 as it happens since ADR-0052: the shop owner makes the token and runs
 * the check in their dashboard; a developer cannot run it alone (G10). The
 * address must be public and `https://` (G47, addresses.py), is never followed
 * through a redirect (GenericClient), and is the one that gets connected, which
 * nothing can change afterwards (G52).
 */
const CHECK_STEPS: { title: string; who: string; note: React.ReactNode }[] = [
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
              It never changes anything in the shop — no orders, no prices, no stock. Every address
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
              It describes every address and every field. Keep it open while you build — or point a
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
            below. Put them under any prefix — {c("/neura/v1")} is the usual one.
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
          <ol className="m-0 flex list-none flex-col gap-0 overflow-hidden rounded-xl border border-line p-0">
            {CHECK_STEPS.map((step, i) => (
              <li
                key={step.title}
                className={`flex gap-3 px-4 py-3.5 ${i < CHECK_STEPS.length - 1 ? "border-b border-[#efefef]" : ""}`}
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
          <Rules
            ordered
            items={[
              <>
                Put the {b("shop token")} FiveNeurals gives you into your bridge&apos;s settings.
              </>,
              <>
                Send FiveNeurals your bridge&apos;s address, for example{" "}
                {c("https://yourshop.example/neura/v1")}.
              </>,
              <>
                FiveNeurals connects your shop and copies its catalogue. The shop owner sees{" "}
                <em>Your shop is connected</em> ticked in their dashboard.
              </>,
            ]}
          />
          <P>
            {b("The shop token is a secret.")} Never put it in a page, a browser or a public code
            repository. We store it encrypted and never show it, not even to the shop owner.
          </P>
        </Section>

        <Section id="chat" title="5 · Add the chat box">
          <P>
            One line on every page of your shop. FiveNeurals makes the chat box key for your
            shop&apos;s exact address.
          </P>
          <Pre>{`<script src="https://${NEURA_HOST}/v1/widget/widget.js" async
        data-neura-key="fn_pk_…"></script>`}</Pre>
          <Rules
            items={[
              <>
                {b("The key is public, and that's fine.")} It only works from your shop&apos;s
                address. {c("www.")} and no {c("www.")} are different addresses.
              </>,
              <>
                {b("It can't break your page.")} One file, no dependencies. It draws itself in its
                own box, so your styles don&apos;t reach it.
              </>,
              <>
                {b("Strict content security policy?")} Allow our address in {c("script-src")} and{" "}
                {c("connect-src")}. No {c("unsafe-inline")} needed.
              </>,
            ]}
          />
          <Table head={["Attribute", "What it does"]} rows={ATTRIBUTES} />
        </Section>

        <Section
          id="views"
          title={
            <>
              Optional: product views{" "}
              <span className="font-normal text-quiet">(for NEURA-SELL&apos;s Sold out list)</span>
            </>
          }
        >
          <P>
            If the shop owner wants the Sold out list, your shop&apos;s server tells NEURA when a
            shopper opens a product or adds one to the basket. FiveNeurals first records a data
            agreement with the shop, then gives you a {b("secret")} key that can send them.
          </P>
          <Pre>{`POST https://${NEURA_HOST}/v1/observe/events
Authorization: Bearer fn_sk_…     ← secret, from your server only

type: product.viewed (with in_stock) · cart.added`}</Pre>
          <Rules
            ordered
            items={[
              <>
                {b("Off by default, and off means nothing is sent.")} Check the switch before the
                event exists.
              </>,
              <>{b("From your server, never from the browser.")} A public key is refused.</>,
              <>
                {b("Never send the shopper's cookie.")} Send a session id hashed with a key only you
                hold, and no name, email or address.
              </>,
            ]}
          />
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
