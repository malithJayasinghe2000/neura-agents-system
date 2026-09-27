"use client";

/**
 * One product's suggestions, and the owner's way to change them — ADR-0050.
 *
 * Closed, it shows what a shopper's basket shows now and who decided. Open, it
 * starts from that same list, so "change" means *edit what is there* rather than
 * *start again*: remove what is wrong, add what is better, save. The three rules
 * the owner approved are why the buttons are what they are:
 *
 * 1. **The owner's choice wins** — once saved, nothing automatic replaces it.
 *    Saving an empty list is allowed and means "show nothing for this product".
 * 2. **Same for every shopper** — there is nothing per-shopper to configure.
 * 3. **Only our suggestions change** — nothing here edits the shop's products.
 */

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Plus, X } from "lucide-react";
import { chooseSuggestions, findProducts, resetSuggestions, type PickedProduct } from "@/lib/api";
import type { ProductSuggestions, Suggested } from "@/lib/suggestions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const MODE_LABEL: Record<ProductSuggestions["mode"], string> = {
  owner: "Your choice",
  automatic: "Chosen by AI",
  pending: "Automatic",
};

export function SuggestionEditor({
  tenantId,
  product,
  maxChosen,
}: {
  tenantId: string;
  product: ProductSuggestions;
  maxChosen: number;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Suggested[]>(product.suggested.slice(0, maxChosen));
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PickedProduct[]>([]);
  const [pending, startTransition] = useTransition();

  const full = draft.length >= maxChosen;
  const taken = new Set([product.product_id, ...draft.map((item) => item.product_id)]);

  function open() {
    setDraft(product.suggested.slice(0, maxChosen));
    setResults([]);
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
          product.product_id,
          draft.map((item) => item.product_id),
        );
        setEditing(false);
        toast.success("Saved. Shoppers see your choice from now on.");
        router.refresh();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "That was not saved.");
      }
    });
  }

  function backToAutomatic() {
    startTransition(async () => {
      try {
        await resetSuggestions(tenantId, product.product_id);
        setEditing(false);
        toast.success("Back to automatic.");
        router.refresh();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "That was not saved.");
      }
    });
  }

  return (
    <li className="space-y-3 py-4" data-product={product.product_id}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{product.title ?? `Product ${product.product_id}`}</span>
            <Badge variant={product.mode === "owner" ? "default" : "outline"}>
              {MODE_LABEL[product.mode]}
            </Badge>
          </div>
          {!editing ? <Current product={product} /> : null}
        </div>
        {!editing ? (
          <Button size="sm" variant="outline" onClick={open}>
            Change
          </Button>
        ) : null}
      </div>

      {editing ? (
        <div className="space-y-3 rounded-lg border p-3">
          <div className="space-y-1.5">
            <p className="text-xs tracking-wide text-muted-foreground uppercase">
              Suggest with this product ({draft.length} of {maxChosen})
            </p>
            {draft.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing. Saving this shows no suggestion for this product.
              </p>
            ) : (
              <ol className="space-y-1">
                {draft.map((item, index) => (
                  <li key={item.product_id} className="flex items-center gap-2 text-sm">
                    <span className="w-4 text-muted-foreground tabular-nums">{index + 1}.</span>
                    <span>{item.title ?? `Product ${item.product_id}`}</span>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Remove ${item.title ?? item.product_id}`}
                      onClick={() =>
                        setDraft(draft.filter((other) => other.product_id !== item.product_id))
                      }
                    >
                      <X aria-hidden />
                    </Button>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              search();
            }}
          >
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find a product in your shop"
              aria-label="Find a product"
              maxLength={100}
            />
            <Button type="submit" size="sm" variant="secondary" disabled={pending}>
              Search
            </Button>
          </form>

          {results.length > 0 ? (
            <ul className="space-y-1">
              {results.map((result) => (
                <li key={result.product_id} className="flex items-center gap-2 text-sm">
                  <Button
                    size="icon-xs"
                    variant="outline"
                    aria-label={`Add ${result.title ?? result.product_id}`}
                    disabled={full || taken.has(result.product_id)}
                    onClick={() => setDraft([...draft, result])}
                  >
                    <Plus aria-hidden />
                  </Button>
                  <span className={taken.has(result.product_id) ? "text-muted-foreground" : ""}>
                    {result.title ?? `Product ${result.product_id}`}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" onClick={save} disabled={pending}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={pending}>
              Cancel
            </Button>
            {product.mode === "owner" ? (
              <Button size="sm" variant="ghost" onClick={backToAutomatic} disabled={pending}>
                Back to automatic
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function Current({ product }: { product: ProductSuggestions }) {
  if (product.suggested.length > 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {product.suggested.map((item) => item.title ?? `Product ${item.product_id}`).join(" · ")}
      </p>
    );
  }
  return (
    <p className="text-sm text-muted-foreground">
      {product.mode === "owner"
        ? "You chose to show nothing with this product."
        : "Decided from this product's own words the first time a shopper's basket shows it."}
    </p>
  );
}
