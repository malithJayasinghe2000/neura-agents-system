/**
 * Screen 7 — Suggestions. ADR-0050: the shop owner may choose what is
 * suggested with each product, and their choice wins.
 *
 * Redesigned 2026-09-28 from the owner's approved design (console.md §3.6).
 * Before, every product whose suggestions came from its own words read
 * *"Automatic"* over an empty row: a word-path answer is worked out live on a
 * shopper's basket and never stored, so the list had nothing to show — and the
 * owner could change what they could not see. Now:
 *
 * - **Products on the left, one open on the right**, like Review; filter chips
 *   say who decides each (*Your choice · Chosen by AI · Automatic*) with counts.
 * - **Opening a product asks the shop what a basket would show with it now** —
 *   the basket's own code, the same heading and cards a shopper gets, and **no
 *   model run and nothing saved** (`console.py`'s `preview`). The shop is asked
 *   only when the owner opens a product.
 * - When nothing is shown it says **why** (no category in the shop, nothing
 *   matched, …), and when the AI tried and found nothing it says what it
 *   looked for — so "the AI found nothing" and "the AI never ran" read apart.
 * - *Change these* opens the same editor as before, in the panel.
 *
 * Served by SELL's own routes (`/v1/sell/console/...`), so a shop without SELL
 * gets a plain sentence rather than an empty list pretending to be one.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  EyeOff,
  Search,
  ShoppingBag,
  Sparkles,
} from "lucide-react";
import {
  AskAgain,
  ChoiceEditor,
  SAME_FOR_EVERY_SHOPPER,
} from "@/components/suggestions/choice-editor";
import { CategorySelect } from "@/components/suggestions/category-select";
import { KeepInView } from "@/components/suggestions/keep-in-view";
import { fromApi, hasSession } from "@/lib/server-api";
import {
  MODE_FILTERS,
  MODE_LABEL,
  aiNote,
  money,
  sourceLine,
  whyNothing,
  type Preview,
  type ProductSuggestions,
  type SuggestionMode,
  type SuggestionsMeta,
  type SuggestionsPage,
} from "@/lib/suggestions";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const SELL = "/v1/sell/console";

type View = { q: string; mode: string; category: string; after: string; product: string };

export default async function SuggestionsScreen({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<Partial<View>>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const raw = await searchParams;
  const view: View = {
    q: raw.q ?? "",
    mode: raw.mode ?? "",
    category: raw.category ?? "",
    after: raw.after ?? "",
    product: raw.product ?? "",
  };
  const shop = encodeURIComponent(tenantId);
  const base = `/console/${shop}/suggestions`;

  const listQuery = new URLSearchParams();
  if (view.q) listQuery.set("q", view.q);
  if (view.mode) listQuery.set("mode", view.mode);
  if (view.category) listQuery.set("category", view.category);
  if (view.after) listQuery.set("after", view.after);

  // The preview is fetched only when a product is open: it is the one request
  // on this screen that reaches the shop, and it happens when the owner asks.
  const [list, preview] = await Promise.all([
    fromApi<SuggestionsPage>(
      `/shops/${shop}/suggestions${listQuery.size ? `?${listQuery}` : ""}`,
      SELL,
    ),
    view.product
      ? fromApi<Preview>(
          `/shops/${shop}/suggestions/${encodeURIComponent(view.product)}/preview`,
          SELL,
        )
      : Promise.resolve(null),
  ]);

  /** This screen's address with some of its state changed — the rest kept. */
  const link = (change: Partial<View>): string => {
    const next = { ...view, ...change };
    const query = new URLSearchParams();
    for (const key of ["q", "mode", "category", "after", "product"] as const) {
      if (next[key]) query.set(key, next[key]);
    }
    return query.size ? `${base}?${query}` : base;
  };

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Suggestions</h1>
        <p className="text-muted-foreground">
          What a shopper&apos;s basket suggests with each product — and your way to change it.
        </p>
      </div>

      {!list.ok ? (
        <Alert variant={list.status === 403 ? "default" : "destructive"}>
          <AlertTitle>
            {list.status === 404
              ? "No such shop, or no access to it"
              : list.status === 403
                ? "Suggestions are not part of this shop's plan"
                : "Could not load"}
          </AlertTitle>
          <AlertDescription>{list.message}</AlertDescription>
        </Alert>
      ) : (
        <>
          <Chips
            counts={(list.meta as SuggestionsMeta).counts}
            current={view.mode}
            link={(mode) => link({ mode, after: "" })}
          />

          <div className="lg:grid lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start lg:gap-5">
            <div className={cn("space-y-3", view.product && "hidden lg:block")}>
              <ProductList
                data={list.data}
                meta={list.meta as SuggestionsMeta}
                view={view}
                link={link}
              />
            </div>

            {preview ? (
              <Panel
                tenantId={tenantId}
                productId={view.product}
                preview={preview}
                maxChosen={list.data.max_chosen}
                back={link({ product: "" })}
              />
            ) : (
              <div className="hidden space-y-2 rounded-2xl border border-dashed p-8 text-center lg:sticky lg:top-6 lg:block">
                <p className="font-medium">
                  Open a product to see what a shopper&apos;s basket shows with it
                </p>
                <p className="text-sm text-muted-foreground">
                  Your shop is asked when you open one. No AI runs, and nothing is saved.
                </p>
                <p className="text-sm text-muted-foreground">{SAME_FOR_EVERY_SHOPPER}</p>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}

function Chips({
  counts,
  current,
  link,
}: {
  counts: SuggestionsMeta["counts"];
  current: string;
  link: (mode: string) => string;
}) {
  return (
    <nav aria-label="Show products that are" className="flex flex-wrap gap-2">
      {MODE_FILTERS.map((filter) => {
        const on = current === filter.key;
        const count = counts ? counts[filter.key || "all"] : undefined;
        return (
          <Link
            key={filter.key || "all"}
            href={link(filter.key)}
            aria-current={on ? "page" : undefined}
            className={cn(
              "inline-flex h-10 items-center gap-1.5 rounded-full border px-4 text-sm font-medium transition-colors",
              on
                ? "border-foreground bg-foreground text-background"
                : "text-muted-foreground hover:border-foreground/40 hover:text-foreground",
            )}
          >
            {filter.label}
            {count !== undefined ? <span className="tabular-nums">{count}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}

function ProductList({
  data,
  meta,
  view,
  link,
}: {
  data: SuggestionsPage;
  meta: SuggestionsMeta;
  view: View;
  link: (change: Partial<View>) => string;
}) {
  const filtered = Boolean(view.q || view.mode || view.category);
  const menu = meta.categories;
  return (
    <>
      <form action="" className="flex gap-2">
        {view.mode ? <input type="hidden" name="mode" value={view.mode} /> : null}
        {view.category ? <input type="hidden" name="category" value={view.category} /> : null}
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            name="q"
            defaultValue={view.q}
            placeholder="Find one of your products"
            aria-label="Find one of your products"
            className="h-11 pl-9"
          />
        </div>
        <Button type="submit" variant="secondary" className="h-11 px-4">
          Find
        </Button>
      </form>

      {menu ? (
        <CategorySelect
          current={view.category}
          options={[
            { value: "", label: "All categories", href: link({ category: "", after: "" }) },
            ...menu.named.map((option) => ({
              value: option.id,
              label: `${option.name} (${option.count})`,
              href: link({ category: option.id, after: "" }),
            })),
            ...(menu.none > 0 || view.category === "none"
              ? [
                  {
                    value: "none",
                    label: `No category (${menu.none})`,
                    href: link({ category: "none", after: "" }),
                  },
                ]
              : []),
          ]}
        />
      ) : null}

      <div className="overflow-hidden rounded-2xl border">
        {data.products.length === 0 ? (
          <div className="space-y-2 p-5 text-sm text-muted-foreground">
            <p>
              {filtered
                ? "No product matches."
                : "No products yet. They appear here once your shop's catalogue has synced."}
            </p>
            {filtered ? (
              <Link href={link({ q: "", mode: "", category: "", after: "" })} className="underline">
                Show every product
              </Link>
            ) : null}
          </div>
        ) : (
          <ul data-product-list className="divide-y">
            {data.products.map((item) => (
              <li key={item.product_id}>
                <Row
                  item={item}
                  current={item.product_id === view.product}
                  href={link({ product: item.product_id })}
                />
              </li>
            ))}
          </ul>
        )}
        <KeepInView productId={view.product} />
        <div className="space-y-1 border-t bg-muted/30 px-4 py-2.5 text-xs text-muted-foreground">
          <p>A product added to your shop appears here after its next sync.</p>
          {meta.counted_all === false ? <p>The counts cover the first 2,000 products.</p> : null}
        </div>
      </div>

      <Pager shown={data.products.length} meta={meta} filtered={filtered} link={link} />
    </>
  );
}

/**
 * *"Showing 26–38 of 38"*, and the two ways out of this page — the same shape
 * as Conversations, with *Previous / Next* because products have no date order.
 * The position comes from the server's count, never from this page counting
 * its own clicks.
 */
function Pager({
  shown,
  meta,
  filtered,
  link,
}: {
  shown: number;
  meta: SuggestionsMeta;
  filtered: boolean;
  link: (change: Partial<View>) => string;
}) {
  if (meta.total === undefined || meta.total === 0) return null;
  const from = (meta.offset ?? 0) + 1;
  const through = (meta.offset ?? 0) + shown;
  const previous = meta.has_previous ? link({ after: meta.previous_cursor ?? "" }) : null;
  const next = meta.has_more && meta.next_cursor ? link({ after: meta.next_cursor }) : null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted-foreground">
        Showing {from}–{through} of {meta.total}
        {filtered ? " that match" : ""}
      </p>
      <div className="flex gap-2">
        {previous ? (
          <Button
            variant="outline"
            className="h-10 px-3"
            nativeButton={false}
            render={<Link href={previous} />}
          >
            <ChevronLeft aria-hidden />
            Previous
          </Button>
        ) : (
          <Button variant="outline" className="h-10 px-3" disabled>
            <ChevronLeft aria-hidden />
            Previous
          </Button>
        )}
        {next ? (
          <Button
            variant="outline"
            className="h-10 px-3"
            nativeButton={false}
            render={<Link href={next} />}
          >
            Next
            <ChevronRight aria-hidden />
          </Button>
        ) : (
          <Button variant="outline" className="h-10 px-3" disabled>
            Next
            <ChevronRight aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );
}

function Row({
  item,
  current,
  href,
}: {
  item: ProductSuggestions;
  current: boolean;
  href: string;
}) {
  return (
    <Link
      href={href}
      aria-current={current ? "true" : undefined}
      data-product={item.product_id}
      className={cn(
        "flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/50",
        current && "bg-muted",
      )}
    >
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate text-sm", current ? "font-semibold" : "font-medium")}>
          {item.title ?? `Product ${item.product_id}`}
        </span>
        <span className="block truncate text-xs text-muted-foreground">{catalogueLine(item)}</span>
      </span>
      <ModeBadge mode={item.mode} />
    </Link>
  );
}

function ModeBadge({ mode }: { mode: SuggestionMode }) {
  return (
    <Badge
      variant={mode === "owner" ? "default" : mode === "automatic" ? "secondary" : "outline"}
      className="shrink-0"
    >
      {MODE_LABEL[mode]}
    </Badge>
  );
}

/** "Trousers & Jeans · $62.00" — or "No category", which is itself a reason. */
function catalogueLine(item: ProductSuggestions): string {
  const categories = item.categories.length ? item.categories.join(", ") : "No category";
  return item.price ? `${categories} · ${money(item.price)}` : categories;
}

function Panel({
  tenantId,
  productId,
  preview,
  maxChosen,
  back,
}: {
  tenantId: string;
  productId: string;
  preview: Awaited<ReturnType<typeof fromApi<Preview>>>;
  maxChosen: number;
  back: string;
}) {
  const product = preview.ok ? preview.data.product : null;
  const title = product?.title ?? `Product ${productId}`;

  return (
    <section
      aria-label="The product open"
      // Stays on screen while the list scrolls with the page; a panel taller
      // than the window (the editor open) scrolls on its own.
      className="space-y-5 rounded-2xl border p-5 sm:p-6 lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:overflow-y-auto"
      data-open-product={productId}
    >
      <Button
        variant="ghost"
        size="sm"
        className="-ml-2 h-9 lg:hidden"
        nativeButton={false}
        render={<Link href={back} />}
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        All products
      </Button>

      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          {product ? (
            <p className="text-sm text-muted-foreground">{catalogueLine(product)}</p>
          ) : null}
        </div>
        {product ? <ModeBadge mode={product.mode} /> : null}
      </header>

      {!preview.ok ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load this product</AlertTitle>
          <AlertDescription>{preview.message}</AlertDescription>
        </Alert>
      ) : (
        <Shown preview={preview.data} />
      )}

      {preview.ok && product ? (
        <ChoiceEditor
          key={product.product_id}
          tenantId={tenantId}
          productId={product.product_id}
          productTitle={title}
          initial={
            product.mode === "owner"
              ? product.suggested
              : preview.data.suggestions.map((card) => ({
                  product_id: card.id,
                  title: card.title,
                  price: card.price ? { amount: card.price, currency: card.currency ?? "" } : null,
                }))
          }
          maxChosen={maxChosen}
          isOwner={product.mode === "owner"}
          startLabel={
            preview.data.suggestions.length > 0 || product.mode === "owner"
              ? "Change these"
              : "Choose suggestions"
          }
        />
      ) : null}
    </section>
  );
}

/** What a shopper's basket shows with the product now, and where it came from. */
function Shown({ preview }: { preview: Preview }) {
  if (!preview.reachable) {
    return (
      <div className="space-y-2 rounded-xl border border-dashed p-4">
        <p className="font-semibold">Your shop did not answer just now</p>
        <p className="text-sm text-muted-foreground">
          So this cannot say what a shopper&apos;s basket shows with this product. Nothing has
          changed for your shoppers.
        </p>
        <AskAgain />
      </div>
    );
  }

  const note = aiNote(preview);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          What a shopper&apos;s basket shows with it now
        </p>
        <AskAgain />
      </div>

      {preview.suggestions.length > 0 ? (
        <>
          <div className="space-y-3 rounded-xl border bg-muted/30 p-4">
            <p className="font-semibold">{preview.heading}</p>
            <ul className="grid gap-3 sm:grid-cols-2">
              {preview.suggestions.map((card) => (
                <li
                  key={card.id}
                  className="flex items-center gap-3 rounded-lg border bg-background p-2.5"
                >
                  <span className="flex size-12 shrink-0 items-center justify-center rounded-md bg-muted">
                    <ShoppingBag className="size-5 text-muted-foreground" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    {card.url ? (
                      <a
                        href={card.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block text-sm font-medium underline-offset-3 hover:underline"
                      >
                        {card.title}
                      </a>
                    ) : (
                      <span className="block text-sm font-medium">{card.title}</span>
                    )}
                    <span className="block text-xs text-muted-foreground">
                      {[
                        card.price ? money({ amount: card.price, currency: card.currency }) : "",
                        card.in_stock === "true" ? "In stock" : "Out of stock",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <p className="text-sm text-muted-foreground">{sourceLine(preview)}</p>
        </>
      ) : (
        <div className="space-y-1.5 rounded-xl border border-dashed p-4">
          <p className="flex items-center gap-2 font-semibold">
            <EyeOff className="size-4 text-muted-foreground" aria-hidden />
            Nothing is shown with this product
          </p>
          <p className="text-sm text-muted-foreground">{whyNothing(preview)}</p>
        </div>
      )}

      {note ? (
        <p className="flex items-start gap-2.5 rounded-lg bg-muted/60 px-3.5 py-3 text-sm">
          <Sparkles className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          {note}
        </p>
      ) : null}
    </div>
  );
}
