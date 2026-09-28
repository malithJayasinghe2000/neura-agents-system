/**
 * Screen 6 — Sold out. ADR-0046 stage 1, redesigned 2026-09-28 from the
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
 */
import { redirect } from "next/navigation";
import { CheckCircle2, ExternalLink, PackageX, XCircle } from "lucide-react";
import { CheckAgain } from "@/components/sold-out/check-again";
import { When } from "@/components/when";
import { fromApi, hasSession } from "@/lib/server-api";
import { notCheckedLine, opened, type SoldOut, type SoldOutProduct } from "@/lib/sold-out";
import { money } from "@/lib/suggestions";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default async function SoldOutPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // `stock=now`: the one request on this screen that reaches the shop, made
  // because the owner opened it. Home reads the same route without it.
  const result = await fromApi<SoldOut>(
    `/shops/${encodeURIComponent(tenantId)}/sold-out?stock=now`,
  );

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Sold out</h1>
        <p className="text-muted-foreground">
          Products shoppers wanted while you had none, so you know what to restock.
        </p>
      </div>

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

function IsItWorking({ soldOut }: { soldOut: SoldOut }) {
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
