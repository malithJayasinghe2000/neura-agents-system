/**
 * A shop's Home — what needs the owner, and how the assistant is set up.
 *
 * New on 2026-09-27, from the owner's approved mockup. Opening a shop used to
 * land on Conversations; an owner who is not technical needs *"what should I do
 * today?"* answered first. Built entirely from endpoints the other screens
 * already use, so it adds no data and no new way to reach any:
 *
 * | section     | read from                                   |
 * |:--|:--|
 * | the mode    | `/usage` — `withheld`                        |
 * | Needs you   | `/review/scorecard` — replies not yet graded; `/usage` — handed to a person |
 * | Last 7 days | `/usage?period=7d` — counts, and the server's caveat for them **by key** |
 * | Your setup  | `/store`, SELL's `/suggestions`, `/sold-out` |
 *
 * **The rules the rest of the console keeps, kept here** (console.md §3.5): the
 * mode is stated before any figure, because true numbers about work no shopper
 * saw are the most misleading page this console could produce; every count
 * names its period; there is no rate; and the one caveat under the counts is the
 * server's sentence, chosen by its key, not words written in this file.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowRight, Eye, EyeOff, Info } from "lucide-react";
import { When } from "@/components/when";
import { fromApi, hasSession } from "@/lib/server-api";
import type { Scorecard } from "@/lib/review";
import type { ShopView } from "@/lib/shop";
import type { SoldOut } from "@/lib/sold-out";
import type { SuggestionsMeta, SuggestionsPage } from "@/lib/suggestions";
import type { Usage } from "@/lib/usage";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export default async function ShopHome({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const shop = encodeURIComponent(tenantId);
  const base = `/console/${shop}`;

  const [usage, card, store, soldOut, suggestions] = await Promise.all([
    fromApi<Usage>(`/shops/${shop}/usage?period=7d`),
    fromApi<Scorecard>(`/shops/${shop}/review/scorecard`),
    fromApi<ShopView>(`/shops/${shop}/store`),
    fromApi<SoldOut>(`/shops/${shop}/sold-out`),
    // SELL's own route: the API that mounts it never learns an agent's name.
    fromApi<SuggestionsPage>(`/shops/${shop}/suggestions`, "/v1/sell/console"),
  ]);

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Home</h1>
        <p className="text-muted-foreground">What needs you, and how your assistant is set up.</p>
      </div>

      {!usage.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {usage.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {usage.status === 404
              ? "Your account does not hold a live membership for this shop."
              : usage.message}
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <Mode practice={usage.data.withheld} reviewHref={`${base}/review`} />

          <NeedsYou
            base={base}
            waiting={card.ok ? card.data.ungraded : null}
            handed={usage.data.totals.escalations}
            connected={store.ok ? store.data.connected : null}
          />

          <LastSevenDays usage={usage.data} usageHref={`${base}/usage?period=7d`} />

          <section className="space-y-3" aria-labelledby="setup">
            <h2 id="setup" className="text-lg font-semibold">
              Your setup
            </h2>
            <div className="grid gap-3 md:grid-cols-3">
              <CatalogueCard store={store.ok ? store.data : null} href={`${base}/shops`} />
              <SuggestionsCard
                page={suggestions.ok ? suggestions.data : null}
                meta={suggestions.ok ? (suggestions.meta as SuggestionsMeta) : null}
                forbidden={!suggestions.ok && suggestions.status === 403}
                href={`${base}/suggestions`}
              />
              <SoldOutCard soldOut={soldOut.ok ? soldOut.data : null} href={`${base}/sold-out`} />
            </div>
          </section>
        </>
      )}
    </>
  );
}

/** Said before any figure — see the module docstring. */
function Mode({ practice, reviewHref }: { practice: boolean; reviewHref: string }) {
  const Icon = practice ? EyeOff : Eye;
  return (
    <section
      aria-label="Assistant mode"
      className="flex items-start gap-3.5 rounded-xl border bg-muted/40 px-4 py-4 sm:px-5"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-lg border bg-background">
        <Icon className="size-4.5" aria-hidden />
      </span>
      <div className="space-y-1">
        <p className="font-semibold">
          {practice ? "Practice mode is on" : "Your assistant is live"}
        </p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {practice ? (
            <>
              Your assistant writes a reply to every shopper, but no shopper sees it yet. Each reply
              waits in{" "}
              <Link className="text-foreground underline underline-offset-3" href={reviewHref}>
                Review
              </Link>{" "}
              until you check it.
            </>
          ) : (
            "Shoppers see your assistant's replies as soon as it writes them."
          )}
        </p>
      </div>
    </section>
  );
}

/**
 * Each item is one counted fact, said as a sentence, with one thing to do about
 * it. An item appears only when it is true — a list that always has rows is a
 * list an owner learns to skip.
 */
function NeedsYou({
  base,
  waiting,
  handed,
  connected,
}: {
  base: string;
  waiting: number | null;
  handed: number;
  connected: boolean | null;
}) {
  const items: Need[] = [];

  if (connected === false) {
    items.push({
      figure: null,
      title: "Your online shop isn't connected yet",
      detail:
        "Until it is, your assistant has no products or orders to read. Connecting is done outside the console for now — Shop connection says how.",
      action: "Shop connection",
      href: `${base}/shops`,
      primary: true,
    });
  }
  if (waiting) {
    items.push({
      figure: waiting,
      title:
        waiting === 1 ? "reply is waiting for your review" : "replies are waiting for your review",
      detail: "Your assistant wrote them. Mark each one good or bad.",
      action: "Review now",
      href: `${base}/review`,
      primary: true,
    });
  }
  if (handed > 0) {
    items.push({
      figure: handed,
      title:
        handed === 1
          ? "conversation was handed to a person"
          : "conversations were handed to a person",
      detail: "In the last 7 days. Your assistant stopped and asked for someone on your team.",
      action: "See them",
      href: `${base}/conversations?state=escalated`,
      primary: false,
    });
  }

  return (
    <section className="space-y-3" aria-labelledby="needs-you">
      <h2 id="needs-you" className="text-lg font-semibold">
        Needs you
      </h2>
      {items.length === 0 ? (
        <p className="rounded-xl border px-4 py-4 text-sm text-muted-foreground sm:px-5">
          Nothing needs you right now. Replies waiting for review and conversations handed to a
          person will show up here.
        </p>
      ) : (
        <ul className="divide-y overflow-hidden rounded-xl border">
          {items.map((item) => (
            <li
              key={item.href}
              className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-5 sm:px-5"
            >
              <div className="flex min-w-0 flex-1 items-baseline gap-3 sm:items-center sm:gap-5">
                {item.figure !== null ? (
                  <span className="min-w-10 text-3xl font-semibold tracking-tight tabular-nums">
                    {item.figure}
                  </span>
                ) : null}
                <div className="min-w-0 space-y-0.5">
                  <p className="font-medium">{item.title}</p>
                  <p className="text-sm text-muted-foreground">{item.detail}</p>
                </div>
              </div>
              <Button
                variant={item.primary ? "default" : "outline"}
                className="h-10 px-4 sm:shrink-0"
                nativeButton={false}
                render={<Link href={item.href} />}
              >
                {item.action}
                <ArrowRight aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type Need = {
  figure: number | null;
  title: string;
  detail: string;
  action: string;
  href: string;
  primary: boolean;
};

function LastSevenDays({ usage, usageHref }: { usage: Usage; usageHref: string }) {
  const caveat = usage.caveats.find((c) => c.key === "handed_to_a_person");
  const figures: [number, string][] = [
    [usage.totals.conversations, "conversations"],
    [usage.totals.escalations, "handed to a person"],
    [usage.totals.blocked, "blocked as attacks"],
  ];

  return (
    <section className="space-y-3" aria-labelledby="last-seven-days">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="last-seven-days" className="text-lg font-semibold">
          Last 7 days
        </h2>
        {usage.period.since ? (
          <span className="text-sm text-muted-foreground">
            <When iso={usage.period.since} date /> – <When iso={usage.period.through} date />
          </span>
        ) : null}
      </div>
      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        {figures.map(([value, label]) => (
          <div key={label} className="space-y-1 rounded-xl border px-3 py-3.5 sm:px-5 sm:py-4">
            <p className="text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
              {value}
            </p>
            <p className="text-xs text-muted-foreground sm:text-sm">{label}</p>
          </div>
        ))}
      </div>
      {caveat ? (
        <p className="flex items-start gap-2 text-sm leading-relaxed text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {caveat.text}
        </p>
      ) : null}
      <Link
        className="inline-block text-sm font-medium underline-offset-3 hover:underline"
        href={usageHref}
      >
        See usage and cost →
      </Link>
    </section>
  );
}

function SetupCard({
  label,
  headline,
  body,
  note,
  action,
  href,
}: {
  label: string;
  headline: React.ReactNode;
  body: React.ReactNode;
  note?: React.ReactNode;
  action: string;
  href: string;
}) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border px-4 py-4 sm:px-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold">{headline}</p>
      <p className="text-sm">{body}</p>
      {note ? <p className="text-sm leading-relaxed text-muted-foreground">{note}</p> : null}
      <Link
        className="mt-auto pt-2 text-sm font-medium underline-offset-3 hover:underline"
        href={href}
      >
        {action} →
      </Link>
    </div>
  );
}

function CatalogueCard({ store, href }: { store: ShopView | null; href: string }) {
  if (!store || !store.connected) {
    return (
      <SetupCard
        label="Catalogue"
        headline="Not connected"
        body={store ? "Your online shop isn't connected yet." : "Could not be read just now."}
        action="Shop connection"
        href={href}
      />
    );
  }
  const products = store.stores.reduce((sum, s) => sum + (s.catalogue.product ?? 0), 0);
  // The last time products were read, across connections — `null` if never.
  const lastRead = store.stores
    .flatMap((s) => s.syncs)
    .filter((sync) => sync.entity_type === "product" && sync.completed_at)
    .map((sync) => sync.completed_at as string)
    .sort()
    .at(-1);

  return (
    <SetupCard
      label="Catalogue"
      headline={products === 1 ? "1 product" : `${products} products`}
      body={
        lastRead ? (
          <>
            Last read from your shop <When iso={lastRead} />.
          </>
        ) : (
          "Products have never been read from your shop."
        )
      }
      note="Products you add to your shop show up here after the next sync."
      action="Shop connection"
      href={href}
    />
  );
}

/**
 * Counts from the server's own count of every product (`meta.counts`), and only
 * when it counted them all (`counted_all`) — otherwise "for all 50" would be a
 * claim about part of the catalogue dressed as one about the shop. It counted
 * the first page until 2026-09-28, when pages went from 50 to 25 and a
 * 38-product shop lost its number here.
 */
function SuggestionsCard({
  page,
  meta,
  forbidden,
  href,
}: {
  page: SuggestionsPage | null;
  meta: SuggestionsMeta | null;
  forbidden: boolean;
  href: string;
}) {
  if (!page) {
    return (
      <SetupCard
        label="Suggestions"
        headline={forbidden ? "Not in this shop's plan" : "Could not be read"}
        body={
          forbidden
            ? "Suggestions come with the Shopping help assistant, which this shop doesn't have."
            : "Try again in a moment."
        }
        action="Suggestions"
        href={href}
      />
    );
  }
  const counts = meta?.counted_all ? meta.counts : undefined;
  const complete = counts !== undefined;
  const chosen = counts?.owner ?? 0;
  const total = counts?.all ?? 0;

  return (
    <SetupCard
      label="Suggestions"
      headline={
        !complete
          ? "Automatic unless you choose"
          : chosen === 0
            ? `Automatic for all ${total}`
            : `Your choice for ${chosen} of ${total}`
      }
      body={
        complete && chosen === 0
          ? "You haven't chosen suggestions for any product yet."
          : "Products you haven't chosen for are suggested automatically."
      }
      note="When you choose them, your choice always wins."
      action="Choose suggestions"
      href={href}
    />
  );
}

function SoldOutCard({ soldOut, href }: { soldOut: SoldOut | null; href: string }) {
  if (!soldOut) {
    return (
      <SetupCard
        label="Sold out"
        headline="Could not be read"
        body="Try again in a moment."
        action="Open Sold out"
        href={href}
      />
    );
  }
  if (!soldOut.agreement) {
    return (
      <SetupCard
        label="Sold out"
        headline="Not collected"
        body="No data-processing agreement is on record for this shop, so nothing about your shoppers' visits is stored."
        action="Open Sold out"
        href={href}
      />
    );
  }
  const count = soldOut.products.length;
  if (count === 0) {
    return (
      <SetupCard
        label="Sold out"
        headline="Nothing to show"
        body={`No product was viewed while sold out in the last ${soldOut.period.days} days.`}
        note="This also stays empty while product views are switched off in your shop's own settings."
        action="Open Sold out"
        href={href}
      />
    );
  }
  return (
    <SetupCard
      label="Sold out"
      headline={
        soldOut.truncated
          ? `More than ${count} products`
          : count === 1
            ? "1 product"
            : `${count} products`
      }
      body={`Viewed while sold out in the last ${soldOut.period.days} days.`}
      action="Open Sold out"
      href={href}
    />
  );
}
