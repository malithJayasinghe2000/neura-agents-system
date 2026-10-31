/**
 * Screen 6 — Product views (named *Sold out* until G118, R81). ADR-0046 stage 1, redesigned 2026-09-28 from the
 * owner's approved mockup (console.md §3.7).
 *
 * Products shoppers opened while they could not be bought, in the last seven
 * days, most-opened first. It answers one question — *what should I restock?* —
 * and the owner found the first version could not answer it: *VIEWS 2 ·
 * SESSIONS 1* in capitals, an internal id, no word on whether the product was
 * still sold out, and an empty screen that could not say why. Now:
 *
 * - **Each product is a sentence** — *"Opened 3 times, in 1 visit"* — with its
 *   category and price from the synced catalogue.
 * - **Whether it can be bought now**, asked of the shop when this screen opens:
 *   one stock lookup for every product listed (`?stock=now`). *Still sold out* /
 *   *Back in stock* / *Couldn't check* — never yesterday's synced copy, which
 *   said the test shop's sold-out jumper was in stock.
 * - **"Is it working?"** — the agreement, and whether any product view arrived
 *   this week, which is what tells *switched off* from *nothing sold out was
 *   opened*. The switch itself is in the shop and cannot be seen from here.
 * - **"How this works"**, in three steps.
 *
 * Still true, and the reason for the words: **a visit is not a person**, and
 * nothing here names or reaches a shopper — stages 2 and 3 are not approved.
 *
 * **A second tab, *Rarely added to cart*** (ADR-0071, console.md §3.13, the
 * owner's approved mockup 2026-11-01): in-stock products that 10 or more
 * visitors opened in 7 days and fewer than 1 in 10 of them added to the cart.
 * `?tab=rarely`, so Home's line opens it. Facts only, no AI, and this tab never
 * asks the shop anything.
 */
import { redirect } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, ExternalLink, ImageIcon, PackageX, XCircle } from "lucide-react";
import { CheckAgain } from "@/components/sold-out/check-again";
import { When } from "@/components/when";
import { hasSell, shopAssistants } from "@/lib/shop-assistants";
import { fromApi, hasSession } from "@/lib/server-api";
import { PERMISSION, refusal } from "@/lib/roles";
import { NotAllowed } from "@/components/not-allowed";
import {
  addedLine,
  notCheckedLine,
  opened,
  type RarelyAdded,
  type RarelyAddedProduct,
  type SoldOut,
  type SoldOutProduct,
} from "@/lib/sold-out";
import { money } from "@/lib/suggestions";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/** The two tabs. The first is today's list; `?tab=rarely` is ADR-0071's. */
const RARELY = "rarely";

export default async function SoldOutPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const rarely = (await searchParams).tab === RARELY;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.soldOut);
  if (refused) return <NotAllowed refusal={refused} what="Product views" />;
  // Reached by its address only: the menu does not list it for a shop without
  // NEURA-SELL. Said the way Suggestions says it, and nothing is asked of the shop.
  if (!hasSell(await shopAssistants(tenantId))) {
    return (
      <>
        <h1 className="text-2xl font-semibold tracking-tight">Product views</h1>
        <Alert>
          <AlertTitle>Product views is not part of this shop&apos;s plan</AlertTitle>
          <AlertDescription>
            Product views comes with NEURA-SELL, which this shop doesn&apos;t have.
          </AlertDescription>
        </Alert>
      </>
    );
  }
  const shop = encodeURIComponent(tenantId);
  const heading = (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Product views</h1>
        <p className="text-muted-foreground">
          What shoppers looked at and couldn&apos;t buy, or didn&apos;t buy.
        </p>
      </div>
      <Tabs base={`/console/${shop}/sold-out`} rarely={rarely} />
    </>
  );

  if (rarely) {
    const tab = await fromApi<RarelyAdded>(`/shops/${shop}/sold-out/rarely-added`);
    return (
      <>
        {heading}
        {!tab.ok ? (
          <CouldNotLoad status={tab.status} message={tab.message} />
        ) : (
          <div className="space-y-6 lg:grid lg:grid-cols-[minmax(0,1fr)_23rem] lg:items-start lg:gap-6 lg:space-y-0">
            <div className="space-y-3">
              <p className="leading-relaxed">
                Products in stock that many shoppers opened but few added to the cart. Something on
                the page may stop them.
              </p>
              {tab.data.products.length > 0 ? (
                <RarelyList tab={tab.data} />
              ) : (
                <NothingStandsOut tab={tab.data} />
              )}
            </div>
            <div className="space-y-4">
              <IsItWorking soldOut={tab.data} />
              <HowRarelyWorks tab={tab.data} />
            </div>
          </div>
        )}
      </>
    );
  }

  // `stock=now`: the one request on this screen that reaches the shop, made
  // because the owner opened it. Home reads the same route without it.
  const result = await fromApi<SoldOut>(`/shops/${shop}/sold-out?stock=now`);

  return (
    <>
      {heading}

      {!result.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {result.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {result.status === 404
              ? "Your account does not hold a live membership for this shop."
              : result.message}
          </AlertDescription>
        </Alert>
      ) : (
        <div className="space-y-6 lg:grid lg:grid-cols-[minmax(0,1fr)_23rem] lg:items-start lg:gap-6 lg:space-y-0">
          <div className="space-y-3">
            {result.data.products.length > 0 ? (
              <Wanted soldOut={result.data} />
            ) : (
              <NothingListed soldOut={result.data} />
            )}
          </div>
          <div className="space-y-4">
            <IsItWorking soldOut={result.data} />
            <HowThisWorks keptDays={result.data.kept_days} />
          </div>
        </div>
      )}
    </>
  );
}

/** Links, not buttons: each tab has its own address, which Home's line opens. */
function Tabs({ base, rarely }: { base: string; rarely: boolean }) {
  const tab = (href: string, label: string, current: boolean) => (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={cn(
        "-mb-px flex h-10 items-center border-b-2 px-1 text-[15px]",
        current
          ? "border-foreground font-semibold text-foreground"
          : "border-transparent font-medium text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </Link>
  );
  return (
    <nav aria-label="Product views tabs" data-tabs className="flex gap-6 border-b">
      {tab(base, "Sold out", !rarely)}
      {tab(`${base}?tab=${RARELY}`, "Rarely added to cart", rarely)}
    </nav>
  );
}

function CouldNotLoad({ status, message }: { status: number; message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>
        {status === 404 ? "No such shop, or no access to it" : "Could not load"}
      </AlertTitle>
      <AlertDescription>
        {status === 404 ? "Your account does not hold a live membership for this shop." : message}
      </AlertDescription>
    </Alert>
  );
}

function RarelyList({ tab }: { tab: RarelyAdded }) {
  return (
    <>
      <p className="font-medium">Check the price, photos and description.</p>
      <section aria-label="Rarely added to cart" className="overflow-hidden rounded-2xl border">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b px-4 py-3.5 sm:px-5">
          <p className="font-semibold">
            Last {tab.period.days} days · <When iso={tab.period.since} date /> to{" "}
            <When iso={tab.period.through} date />
          </p>
          <p className="text-sm text-muted-foreground">Fewest added first</p>
        </div>
        <ul className="divide-y">
          {tab.products.map((product) => (
            <RarelyRow key={product.product_id} product={product} />
          ))}
        </ul>
      </section>

      {tab.truncated ? (
        <p className="text-sm text-muted-foreground">
          More products were opened and rarely added than this list shows.
        </p>
      ) : null}
      {/* The server's sentences, each shown only when true (ADR-0020 §3). */}
      {tab.caveats.map((caveat) => (
        <p key={caveat} className="text-sm leading-relaxed text-muted-foreground">
          {caveat}
        </p>
      ))}
    </>
  );
}

function RarelyRow({ product }: { product: RarelyAddedProduct }) {
  return (
    <li
      data-product={product.product_id}
      className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <div className="flex min-w-0 flex-1 items-center gap-4">
        {product.image ? (
          // The shop's own photo, from the synced catalogue; the name beside it says what it is.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={product.image}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="size-12 shrink-0 rounded-lg bg-muted object-cover"
          />
        ) : (
          <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-muted">
            <ImageIcon className="size-5 text-muted-foreground" aria-hidden />
          </span>
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <p className="font-semibold">{product.title ?? `Product ${product.product_id}`}</p>
          <p className="text-sm text-muted-foreground">
            <strong className="font-semibold text-foreground">
              {product.visitors === 1 ? "1 visitor" : `${product.visitors} visitors`}
            </strong>
            , {addedLine(product)}
          </p>
          <p className="text-xs text-muted-foreground">
            {product.title ? (
              <>
                {money(product.price) ? `${money(product.price)} · ` : null}last opened{" "}
                <When iso={product.last_viewed_at} date />
              </>
            ) : (
              "Not in your synced catalogue yet"
            )}
          </p>
        </div>
      </div>
      {product.url ? (
        <Button
          variant="outline"
          className="h-11 self-start px-4 sm:h-10 sm:self-center"
          nativeButton={false}
          data-open-page
          render={
            <a
              href={product.url}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open the page for ${product.title ?? "this product"} in a new tab`}
            />
          }
        >
          Open the page
          <ExternalLink className="size-3.5" aria-hidden />
        </Button>
      ) : null}
    </li>
  );
}

/** Two causes, said apart, as on the first tab (console.md §3.13, board 73). */
function NothingStandsOut({ tab }: { tab: RarelyAdded }) {
  return (
    <section data-nothing className="space-y-2 rounded-2xl border p-5 sm:p-7">
      {!tab.agreement ? (
        <>
          <h2 className="text-lg font-semibold">Nothing is collected for this shop</h2>
          <p className="leading-relaxed">
            No data-processing agreement is on record for this shop, so nothing about your
            shoppers&apos; visits is stored. Until one is recorded, this tab stays empty.
          </p>
        </>
      ) : tab.receiving ? (
        <>
          <h2 className="text-lg font-semibold">No product stands out this week</h2>
          <p className="leading-relaxed">
            No product had {tab.min_visitors} or more visitors with fewer than 1 in {tab.one_in}{" "}
            adding it to the cart in the last {tab.period.days} days.
          </p>
        </>
      ) : (
        <>
          <h2 className="text-lg font-semibold">
            No product views arrived in the last {tab.period.days} days
          </h2>
          <p className="leading-relaxed">
            Your shop isn&apos;t sending product views, so there is nothing to count. See{" "}
            <em>Is it working?</em>
            <span className="lg:hidden"> below</span>
            <span className="hidden lg:inline"> on the right</span>.
          </p>
        </>
      )}
    </section>
  );
}

function HowRarelyWorks({ tab }: { tab: RarelyAdded }) {
  return (
    <section aria-labelledby="how-rarely-works" className="space-y-3 rounded-2xl border p-5">
      <h2 id="how-rarely-works" className="font-semibold">
        How this works
      </h2>
      {/* Numbered because it is a sequence: each step needs the one before. */}
      <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
        <li>
          Your shop tells us when a shopper opens a product page, and when they add it to the cart.
          No name, email or address is sent.
        </li>
        <li>We keep it for {tab.kept_days === 1 ? "1 day" : `${tab.kept_days} days`}.</li>
        <li>
          {/* The rule from the server, not numbers typed here. */}A product shows here when{" "}
          {tab.min_visitors} or more visitors opened it while it was in stock, and fewer than 1 in{" "}
          {tab.one_in} of them added it to the cart.
        </li>
      </ol>
      <p className="text-sm text-muted-foreground">
        Nothing here reaches your shoppers, and we never contact them. No AI is used: these are
        counts.
      </p>
    </section>
  );
}

function Wanted({ soldOut }: { soldOut: SoldOut }) {
  const { stock } = soldOut;
  return (
    <>
      <section aria-label="Wanted while sold out" className="overflow-hidden rounded-2xl border">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b px-4 py-3.5 sm:px-5">
          <p className="font-semibold">
            Last {soldOut.period.days} days · <When iso={soldOut.period.since} date /> –{" "}
            <When iso={soldOut.period.through} date />
          </p>
          <p className="text-sm text-muted-foreground">Most-opened first</p>
        </div>

        <ul className="divide-y">
          {soldOut.products.map((product) => (
            <Row key={product.product_id} product={product} checked={Boolean(stock?.answered)} />
          ))}
        </ul>

        {stock ? (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t bg-muted/30 py-1.5 pr-2 pl-4 sm:pl-5">
            <p
              data-stock-line
              className={cn("py-1.5 text-sm", stock.answered ? "text-muted-foreground" : "")}
            >
              {stock.answered
                ? "Asked your shop just now, in one question for every product listed."
                : notCheckedLine(stock)}
            </p>
            <CheckAgain />
          </div>
        ) : null}
      </section>

      {soldOut.truncated ? (
        <p className="text-sm text-muted-foreground">
          More products were opened while sold out than this list shows.
        </p>
      ) : null}
      {/* The server's sentences, each shown only when true (ADR-0020 §3). */}
      {soldOut.caveats.map((caveat) => (
        <p key={caveat} className="text-sm leading-relaxed text-muted-foreground">
          {caveat}
        </p>
      ))}
    </>
  );
}

function Row({ product, checked }: { product: SoldOutProduct; checked: boolean }) {
  const { times, visits } = opened(product);
  const catalogue = [product.categories.join(", "), money(product.price)]
    .filter(Boolean)
    .join(" · ");

  return (
    <li
      data-product={product.product_id}
      className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <span className="hidden size-12 shrink-0 items-center justify-center rounded-lg bg-muted sm:flex">
        <PackageX className="size-5 text-muted-foreground" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        {product.title && product.url ? (
          <a
            href={product.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 font-semibold underline-offset-3 hover:underline"
          >
            {product.title}
            <ExternalLink
              className="size-3.5 text-muted-foreground"
              aria-label="opens in your shop"
            />
          </a>
        ) : (
          // Shown by its id rather than dropped: the demand is real even when
          // the synced catalogue has not caught up with the product.
          <p className="font-semibold">{product.title ?? `Product ${product.product_id}`}</p>
        )}
        <p className="text-sm text-muted-foreground">
          Opened <strong className="font-semibold text-foreground">{times}</strong>, in {visits} ·
          last opened <When iso={product.last_viewed_at} date />
        </p>
        <p className="text-xs text-muted-foreground">
          {product.title ? catalogue : "Not in your synced catalogue yet"}
        </p>
        {product.in_stock_now === true ? (
          <p className="text-sm">
            It can be bought again now. These visits happened while it could not.
          </p>
        ) : null}
      </div>
      <Now value={checked ? product.in_stock_now : null} />
    </li>
  );
}

/**
 * What the shop said just now. *Couldn't check* covers a shop that did not
 * answer and a product it said nothing about — never shown as sold out.
 */
function Now({ value }: { value: boolean | null }) {
  const label =
    value === false ? "Still sold out" : value === true ? "Back in stock" : "Couldn't check";
  return (
    <span
      data-now
      className={cn(
        "inline-flex h-7 shrink-0 items-center self-start rounded-full border px-3 text-sm font-medium sm:self-center",
        value === false && "border-foreground bg-foreground text-background",
        value === true && "border-foreground/40 text-foreground",
        value === null && "border-dashed bg-muted/50 text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}

/** Three different empty screens, because they have three different causes. */
function NothingListed({ soldOut }: { soldOut: SoldOut }) {
  const period = (
    <>
      <When iso={soldOut.period.since} date /> – <When iso={soldOut.period.through} date />
    </>
  );

  if (soldOut.agreement && soldOut.receiving) {
    return (
      <section className="space-y-2 rounded-2xl border p-5 sm:p-7">
        <span className="flex size-11 items-center justify-center rounded-lg bg-muted">
          <CheckCircle2 className="size-5 text-muted-foreground" aria-hidden />
        </span>
        <h2 className="pt-1 text-lg font-semibold">No sold-out product was opened</h2>
        <p className="leading-relaxed">
          Your shop sent product views in the last {soldOut.period.days} days ({period}), and every
          product shoppers opened could be bought. Nothing to restock.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-2 rounded-2xl border border-dashed p-5 sm:p-7">
      <span className="flex size-11 items-center justify-center rounded-lg bg-muted">
        <PackageX className="size-5 text-muted-foreground" aria-hidden />
      </span>
      {soldOut.agreement ? (
        <>
          <h2 className="pt-1 text-lg font-semibold">Nothing to show yet</h2>
          <p className="leading-relaxed">
            Your shop hasn&apos;t sent any product views in the last {soldOut.period.days} days (
            {period}), so there is nothing to count.
          </p>
          <p className="leading-relaxed">
            Usually this means product views are switched off in your shop&apos;s settings. Whoever
            set up your shop can switch them on. After that, this list fills in by itself.
          </p>
        </>
      ) : (
        <>
          <h2 className="pt-1 text-lg font-semibold">Nothing is collected for this shop</h2>
          <p className="leading-relaxed">
            No data-processing agreement is on record for this shop, so nothing about your
            shoppers&apos; visits is stored. Until one is recorded, this screen stays empty.
          </p>
        </>
      )}
    </section>
  );
}

function IsItWorking({
  soldOut,
}: {
  soldOut: Pick<SoldOut, "agreement" | "agreement_since" | "receiving" | "period">;
}) {
  return (
    <section aria-labelledby="is-it-working" className="space-y-3.5 rounded-2xl border p-5">
      <h2 id="is-it-working" className="font-semibold">
        Is it working?
      </h2>
      <ul className="space-y-3">
        <Step
          done={soldOut.agreement}
          title={soldOut.agreement ? "Data agreement on record" : "No data agreement on record"}
          detail={
            soldOut.agreement && soldOut.agreement_since ? (
              <>
                Since <When iso={soldOut.agreement_since} date />
              </>
            ) : (
              "Nothing about your shoppers' visits is stored until one is."
            )
          }
        />
        <Step
          done={soldOut.receiving}
          title="Your shop is sending product views"
          detail={
            soldOut.receiving
              ? `Some arrived in the last ${soldOut.period.days} days`
              : `None arrived in the last ${soldOut.period.days} days`
          }
        />
      </ul>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Product views are switched on or off in your shop&apos;s own settings. We can&apos;t see
        that switch, only whether views arrive.
      </p>
    </section>
  );
}

function Step({ done, title, detail }: { done: boolean; title: string; detail: React.ReactNode }) {
  const Icon = done ? CheckCircle2 : XCircle;
  return (
    <li data-step={done ? "done" : "not-yet"} className="flex items-start gap-2.5">
      <Icon
        className={cn("mt-0.5 size-5 shrink-0", done ? "text-muted-foreground" : "text-foreground")}
        aria-label={done ? "Done" : "Not yet"}
      />
      <span className="space-y-0.5">
        <span className={cn("block text-sm", done ? "font-medium" : "font-semibold")}>{title}</span>
        <span className="block text-sm text-muted-foreground">{detail}</span>
      </span>
    </li>
  );
}

function HowThisWorks({ keptDays }: { keptDays: number }) {
  return (
    <section aria-labelledby="how-this-works" className="space-y-3 rounded-2xl border p-5">
      <h2 id="how-this-works" className="font-semibold">
        How this works
      </h2>
      {/* Numbered because it is a sequence: each step needs the one before. */}
      <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
        <li>A shopper opens a product page in your shop.</li>
        <li>
          Your shop tells us whether it could be bought at that moment. No name, email or address is
          sent.
        </li>
        <li>
          {/* The retention setting, from the server — not a number typed here. */}
          We keep it for {keptDays === 1 ? "1 day" : `${keptDays} days`}. Products that could not be
          bought are listed here, most-opened first.
        </li>
      </ol>
      <p className="text-sm text-muted-foreground">
        Nothing here reaches your shoppers, and we never contact them.
      </p>
    </section>
  );
}
