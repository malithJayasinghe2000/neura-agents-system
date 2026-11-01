"use client";

/**
 * *Change products* on a plan (D20, R124 to R126; ADR-0076): the owner adds,
 * replaces or removes products, **1 to 3**, any the shop sells (a sold-out one
 * says *Sold out now*), and the plan is written again around them, at once. A
 * later *Make it again* keeps them.
 *
 * **When a draft was edited it asks first**, as *Make it again* does: the
 * owner's own words go with the old plan (R102). The page then reads itself
 * again and shows the plan being made.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronDown, Plus, X } from "lucide-react";
import { changePlanProducts, findPlanProducts } from "@/lib/api";
import type { PlanChoice } from "@/lib/calendar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** R125. */
const MOST = 3;

export function ChangeProducts({
  tenantId,
  planId,
  current,
  edited,
}: {
  tenantId: string;
  planId: string;
  /** The plan's products now, in its order. */
  current: PlanChoice[];
  /** Whether the owner saved their own words over a draft. */
  edited: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<PlanChoice[]>(current);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{ products: PlanChoice[]; more: boolean } | null>(null);
  const [searchable, setSearchable] = useState(false);
  const [adding, setAdding] = useState("");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // The chooser: read when the panel opens, then again as the owner types.
  useEffect(() => {
    if (!open) return;
    let live = true;
    const id = window.setTimeout(
      () => {
        findPlanProducts(tenantId, query)
          .then((result) => {
            if (!live) return;
            setFound(result);
            if (result.more) setSearchable(true);
          })
          .catch((caught) => {
            if (live) setError(caught instanceof Error ? caught.message : "Could not load.");
          });
      },
      query ? 250 : 0,
    );
    return () => {
      live = false;
      window.clearTimeout(id);
    };
  }, [open, tenantId, query]);

  const choices = (found?.products ?? []).filter(
    (product) => !chosen.some((held) => held.product_id === product.product_id),
  );
  const toAdd = choices.some((p) => p.product_id === adding)
    ? adding
    : (choices[0]?.product_id ?? "");
  const same =
    chosen.length === current.length &&
    chosen.every((product, index) => product.product_id === current[index]?.product_id);

  async function write() {
    setBusy(true);
    setError("");
    try {
      await changePlanProducts(
        tenantId,
        planId,
        chosen.map((product) => product.product_id),
      );
      setOpen(false);
      setAsking(false);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button
        variant="outline"
        className="h-11 self-start px-4 sm:h-10"
        data-change-products
        onClick={() => {
          setChosen(current);
          setOpen(true);
        }}
      >
        Change products
      </Button>
    );
  }

  return (
    <div
      data-change-products-panel
      className="w-full space-y-4 rounded-xl border bg-muted/30 px-4 py-4 sm:px-5"
    >
      <div className="space-y-1">
        <p className="font-semibold">Products for this plan</p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Choose 1 to 3. Your assistant writes the plan again around them. To swap one, remove it
          and add another.
        </p>
      </div>

      <ul className="divide-y overflow-hidden rounded-lg border bg-background">
        {chosen.map((product) => (
          <li
            key={product.product_id}
            data-chosen-product={product.product_id}
            className="flex items-center gap-3 px-3.5 py-2.5"
          >
            <span className="min-w-0 flex-1 text-sm break-words">
              {product.title ?? "No longer in your synced catalogue"}
            </span>
            {product.in_stock ? null : <SoldOutNow />}
            <Button
              variant="ghost"
              className="h-10 px-3 text-muted-foreground"
              disabled={chosen.length <= 1 || busy}
              aria-label={`Remove ${product.title ?? "this product"}`}
              data-remove-product
              onClick={() =>
                setChosen((was) => was.filter((p) => p.product_id !== product.product_id))
              }
            >
              <X aria-hidden />
              Remove
            </Button>
          </li>
        ))}
      </ul>

      {chosen.length < MOST ? (
        <div className="space-y-2">
          <label htmlFor={`add-product-${planId}`} className="text-sm font-medium">
            Add a product
          </label>
          {searchable ? (
            <Input
              aria-label="Find a product"
              placeholder="Type to find a product"
              className="h-11 sm:h-10"
              value={query}
              data-product-search
              onChange={(event) => setQuery(event.target.value)}
            />
          ) : null}
          <div className="flex flex-col gap-2 sm:flex-row">
            <span className="relative block w-full sm:max-w-md">
              <select
                id={`add-product-${planId}`}
                data-add-product-choice
                value={toAdd}
                disabled={!choices.length || busy}
                onChange={(event) => setAdding(event.target.value)}
                className="h-11 w-full appearance-none rounded-lg border border-input bg-background py-0 pr-10 pl-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60 sm:h-10"
              >
                {choices.length ? null : (
                  <option value="">
                    {found ? "No other product found" : "Loading your products…"}
                  </option>
                )}
                {choices.map((product) => (
                  <option key={product.product_id} value={product.product_id}>
                    {product.title ?? product.product_id}
                    {product.in_stock ? "" : " (sold out now)"}
                  </option>
                ))}
              </select>
              <ChevronDown
                className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
            </span>
            <Button
              variant="outline"
              className="h-11 self-start px-4 sm:h-10"
              disabled={!toAdd || busy}
              data-add-product
              onClick={() => {
                const product = choices.find((p) => p.product_id === toAdd);
                if (product) setChosen((was) => [...was, product]);
                setAdding("");
              }}
            >
              <Plus aria-hidden />
              Add
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          A plan has at most 3 products. Remove one to add another.
        </p>
      )}

      {asking ? (
        <div
          role="alertdialog"
          aria-labelledby={`products-${planId}`}
          className="flex flex-col gap-3 rounded-lg border bg-background px-4 py-3.5 sm:flex-row sm:items-center"
        >
          <p id={`products-${planId}`} className="text-sm font-medium sm:flex-1">
            Your edits will be replaced. Write the plan again?
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              className="h-11 px-4 sm:h-10"
              disabled={busy}
              data-confirm-products
              onClick={write}
            >
              {busy ? "Asking…" : "Write the plan again"}
            </Button>
            <Button
              variant="outline"
              className="h-11 px-4 sm:h-10"
              disabled={busy}
              onClick={() => setAsking(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            className="h-11 px-4 sm:h-10"
            disabled={busy || same || !chosen.length}
            data-write-again
            onClick={() => (edited ? setAsking(true) : write())}
          >
            {busy ? "Asking…" : "Write the plan again"}
          </Button>
          <Button
            variant="outline"
            className="h-11 px-4 sm:h-10"
            disabled={busy}
            onClick={() => {
              setOpen(false);
              setChosen(current);
              setError("");
            }}
          >
            Cancel
          </Button>
        </div>
      )}

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** *Sold out now* (R126): the owner may promote it, knowing. */
export function SoldOutNow() {
  return (
    <span
      data-sold-out-now
      className="inline-flex h-6 shrink-0 items-center rounded-full border border-dashed px-2.5 text-xs font-medium text-muted-foreground"
    >
      Sold out now
    </span>
  );
}
