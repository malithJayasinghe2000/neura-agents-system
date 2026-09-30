import type { Metadata } from "next";
import { NEURA_HOST, OPENAPI_HREF } from "@/lib/site";

/**
 * Guide for developers — canvas board 25, approved by the owner 2026-09-30.
 *
 * Built from the board, with what is true in the code where the board marked
 * something as undecided (ADR-0051 §4): the check tool is had by asking
 * FiveNeurals; FiveNeurals gives the shop token and makes the chat box key.
 * The example output uses the check tool's real check names and messages
 * (neura_commerce/conformance.py). Only the OpenAPI file is published: the
 * written specification names commerce platforms (Rule 1).
 */
export const metadata: Metadata = {
  title: "Guide for developers",
  description:
    "Connect a shop to NEURA: build the bridge, say what your shop can do, check your work, connect, and add the chat box.",
};

const ADDRESSES: [string, string][] = [
  ["GET /health", "What your shop can do — step 2"],
  ["GET /products", "A page of products"],
  ["GET /products/{id}", "One product"],
  ["GET /categories", "Your category tree"],
  ["GET /inventory?variant_ids=", "Stock levels"],
  ["GET /orders", "A page of orders"],
  ["GET /orders/{id}", "One order"],
  ["GET /customers/{id}", "One customer"],
  ["GET /policies", "Returns, shipping and warranty pages"],
];

const CAPABILITIES: [string, string][] = [
  ["product.read", "list and fetch products"],
  ["product.search", "search products by text"],
  ["category.read", "list categories"],
  ["inventory.read", "stock levels"],
  ["order.read", "list and fetch orders"],
  ["order.search", "search orders"],
  ["customer.read", "fetch a customer by id"],
  ["policy.read", "policy pages"],
  ["sync.incremental", "updated_since really filters"],
  ["events.realtime", "you send change messages"],
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

const ON_THIS_PAGE: [string, string][] = [
  ["overview", "Overview"],
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
            {head.map((h) => (
              <th key={h} scope="col" className="px-3 py-2.5 text-[13px] font-medium text-quiet">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, what], i) => (
            <tr key={name} className={i < rows.length - 1 ? "border-b border-[#efefef]" : ""}>
              <td className="px-3 py-2.5 whitespace-nowrap">
                <code className="font-mono text-[0.92em]">{name}</code>
              </td>
              <td className="px-3 py-2.5 text-body">{what}</td>
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
        <section id="overview" className="flex flex-col gap-4">
          <p className="m-0 text-[13px] font-medium text-quiet">For developers</p>
          <h1 className="m-0 text-[30px] leading-[1.15] font-semibold tracking-[-0.02em] md:text-[40px]">
            Connect a shop to NEURA
          </h1>
          <P>
            A shop connects through a {b("bridge")}: a small add-on that answers nine read-only
            addresses from our published specification. NEURA calls them. Nothing in NEURA knows
            which platform your shop runs on, so any shop can connect, including one you built
            yourself.
          </P>
          <div className="flex flex-col gap-2 rounded-xl bg-[#f5f5f5] px-[18px] py-4">
            <span className="text-[15px] font-semibold">
              You&apos;ll get two keys from FiveNeurals
            </span>
            <span className="text-[15px] leading-[1.5] text-body">
              {b("Shop token")} — secret. NEURA sends it to your bridge. It stays on your
              shop&apos;s server.
            </span>
            <span className="text-[15px] leading-[1.5] text-body">
              {b("Chat box key")} — public. It sits in your pages and only works from your
              shop&apos;s address.
            </span>
          </div>
        </section>

        <Section id="build" title="1 · Build the bridge">
          <P>
            Ask FiveNeurals whether a ready-made bridge exists for your shop&apos;s system. If it
            does, install it like any other add-on and go to step 2. If not, build these nine
            addresses. Mount them under any prefix; {c("/neura/v1")} is the convention.
          </P>
          <Table head={["Address", "Returns"]} rows={ADDRESSES} />
          <Rules
            items={[
              <>{b("Everything is GET.")} No address changes anything in your shop.</>,
              <>
                {b("One header:")} {c("Authorization: Bearer <shop token>")} on every address except{" "}
                {c("/health")}. Refuse a request without it.
              </>,
              <>
                {b("Pages by cursor, not page number.")} Return an opaque {c("next_cursor")}; we
                send it back unchanged.
              </>,
              <>
                {b("No format to learn.")} The JSON you return is published as an{" "}
                <a href={OPENAPI_HREF}>OpenAPI file</a>. Point your code generator at it.
              </>,
            ]}
          />
        </Section>

        <Section id="health" title="2 · Say what your shop can do">
          <P>
            {c("/health")} is not a ping. It lists what your shop can do, and that list decides what
            the assistant is allowed to try.
          </P>
          <Pre>{`{
  "status": "ok",
  "spec_version": "1.0",
  "platform": "my-shop",
  "capabilities": ["product.read", "product.search", "category.read",
                   "inventory.read", "order.read", "policy.read"]
}`}</Pre>
          <Table head={["Capability", "Means"]} rows={CAPABILITIES} />
          <P>
            {b("List only what you built.")} Leave something out and the assistant simply
            doesn&apos;t try it. List something you didn&apos;t build and a shopper&apos;s
            conversation breaks.
          </P>
        </Section>

        <Section id="check" title="3 · Check your work">
          <P>
            One command checks every address against the specification and names anything wrong. Ask
            FiveNeurals for the check tool. Fix what it names and run it again. When it&apos;s
            clean, your bridge is done.
          </P>
          <Pre>neura-conformance --url https://yourshop.example/neura/v1 --token $SHOP_TOKEN</Pre>
          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium text-quiet">Example output</span>
            <Pre>{`  ✔ health                       ok
  ✔ auth.required                ok
  ✘ products.search_empty        search_products() raised on an empty query: HTTPStatusError
  ⚠ sync.updated_since           declares sync.incremental but ignores updated_since`}</Pre>
          </div>
          <P>
            A {b("⚠")} matters as much as a {b("✘")}: your {c("/health")} claims something your
            addresses don&apos;t do.
          </P>
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
