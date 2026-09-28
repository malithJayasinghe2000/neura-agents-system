"use client";

/**
 * The owner's way to change one product's suggestions — ADR-0050, moved into
 * the open product's panel by the 2026-09-28 redesign.
 *
 * It starts from what a shopper's basket shows now (or from the owner's own
 * list, when there is one), so "change" means *edit what is there* rather than
 * *start again*. The three rules the owner approved are why the buttons are
 * what they are:
 *
 * 1. **The owner's choice wins** — once saved, nothing automatic replaces it.
 *    Saving an empty list is allowed and means "show nothing for this product".
 * 2. **Same for every shopper** — there is nothing per-shopper to configure.
 * 3. **Only our suggestions change** — nothing here edits the shop's products.
 */

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Plus, RefreshCw, Search, X } from "lucide-react";
import { chooseSuggestions, findProducts, resetSuggestions, type PickedProduct } from "@/lib/api";
import { money } from "@/lib/suggestions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const SAME_FOR_EVERY_SHOPPER =
  "Same for every shopper. A shopper sees at most two, and only ones in stock at that moment. Your choice always wins.";

export function ChoiceEditor({
  tenantId,
  productId,
  productTitle,
  initial,
  maxChosen,
  isOwner,
  startLabel,
}: {
  tenantId: string;
  productId: string;
  productTitle: string;
  /** What the editor opens with: the owner's list, or what a basket shows now. */
  initial: PickedProduct[];
  maxChosen: number;
  isOwner: boolean;
  /** "Change these", or "Choose suggestions" when nothing is shown. */
  startLabel: string;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<PickedProduct[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PickedProduct[] | null>(null);
  const [pending, startTransition] = useTransition();

  const full = draft.length >= maxChosen;
  const taken = new Set([productId, ...draft.map((item) => item.product_id)]);

  function open() {
    setDraft(initial.slice(0, maxChosen));
    setResults(null);
    setQuery("");
    setEditing(true);
  }

  function search() {
    if (!query.trim()) return;
    startTransition(async () => {
      try {
        setResults(await findProducts(tenantId, query.trim()));
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "The search did not work.");
      }
    });
  }

  function save() {
    startTransition(async () => {
      try {
        await chooseSuggestions(
          tenantId,
          productId,
          draft.map((item) => item.product_id),
        );
        setEditing(false);
        toast.success(
          draft.length === 0
            ? "Saved. Nothing is shown with this product now."
            : "Saved. Shoppers see your choice from now on.",
        );
        router.refresh();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "That was not saved.");
      }
    });
  }

  function backToAutomatic() {
    startTransition(async () => {
      try {
        await resetSuggestions(tenantId, productId);
        toast.success("Back to automatic.");
        router.refresh();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "That was not saved.");
      }
    });
  }

  if (!editing) {
    return (
      <div className="space-y-3 border-t pt-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <Button className="h-11 px-5" onClick={open} disabled={pending}>
            {startLabel}
          </Button>
          {isOwner ? (
            <Button
              variant="outline"
              className="h-11 px-4"
              onClick={backToAutomatic}
              disabled={pending}
            >
              Back to automatic
            </Button>
          ) : null}
        </div>
        <p className="text-sm text-muted-foreground">{SAME_FOR_EVERY_SHOPPER}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 border-t pt-4">
      <div className="space-y-1">
        <p className="font-semibold">Your choice for {productTitle}</p>
        <p className="text-sm text-muted-foreground">
          Up to {maxChosen}. Shoppers see the first two that are in stock; the others stand in when
          one sells out.
        </p>
      </div>

      {draft.length === 0 ? (
        <p className="rounded-xl border border-dashed px-4 py-3 text-sm text-muted-foreground">
          No products picked yet. Use Find below to add some.
        </p>
      ) : (
        <ol className="divide-y rounded-xl border">
          {draft.map((item, index) => (
            <li key={item.product_id} className="flex items-center gap-3 px-3 py-2.5">
              <span className="w-5 text-right text-sm text-muted-foreground tabular-nums">
                {index + 1}.
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">
                  {item.title ?? `Product ${item.product_id}`}
                </span>
                {item.price ? (
                  <span className="block text-xs text-muted-foreground">{money(item.price)}</span>
                ) : null}
              </span>
              <Button
                variant="ghost"
                className="h-9"
                aria-label={`Remove ${item.title ?? item.product_id}`}
                onClick={() =>
                  setDraft(draft.filter((other) => other.product_id !== item.product_id))
                }
              >
                <X aria-hidden />
                Remove
              </Button>
            </li>
          ))}
        </ol>
      )}

      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          search();
        }}
      >
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find a product in your shop — try “socks” or “belt”"
            aria-label="Find a product in your shop"
            maxLength={100}
            className="h-11 pl-9"
          />
        </div>
        <Button type="submit" variant="secondary" className="h-11 px-4" disabled={pending}>
          Find
        </Button>
      </form>

      {results !== null ? (
        results.length === 0 ? (
          <p className="text-sm text-muted-foreground">No product in your shop matches that.</p>
        ) : (
          <ul className="space-y-1.5">
            {results.map((result) => (
              <li
                key={result.product_id}
                className="flex items-center gap-3 rounded-lg border px-3 py-2"
              >
                <span
                  className={`min-w-0 flex-1 text-sm ${taken.has(result.product_id) ? "text-muted-foreground" : ""}`}
                >
                  {result.title ?? `Product ${result.product_id}`}
                  {result.price ? (
                    <span className="text-muted-foreground"> · {money(result.price)}</span>
                  ) : null}
                </span>
                <Button
                  variant="outline"
                  className="h-9"
                  aria-label={`Add ${result.title ?? result.product_id}`}
                  disabled={full || taken.has(result.product_id)}
                  onClick={() => setDraft([...draft, result])}
                >
                  <Plus aria-hidden />
                  Add
                </Button>
              </li>
            ))}
          </ul>
        )
      ) : null}

      <div className="flex gap-2 border-t pt-4">
        {/* An empty list is a real choice (ADR-0050: show nothing), so the
            button says so rather than "Save" — nobody turns suggestions off
            for a product without reading that they are. */}
        <Button className="h-11 px-5" onClick={save} disabled={pending}>
          {draft.length === 0 ? "Show nothing with this product" : "Save"}
        </Button>
        <Button
          variant="outline"
          className="h-11 px-4"
          onClick={() => setEditing(false)}
          disabled={pending}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

/**
 * "Asked your shop just now" — and the way to ask again. A refresh of this
 * page, which re-runs the preview: the shop is asked when the owner asks.
 */
export function AskAgain() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-8 text-muted-foreground"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      <RefreshCw className={pending ? "animate-spin" : ""} aria-hidden />
      {pending ? "Asking your shop…" : "Ask your shop again"}
    </Button>
  );
}
