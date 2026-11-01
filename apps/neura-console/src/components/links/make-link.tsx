"use client";

/**
 * Make a link (board 82): **Product**, **Where you'll post it**, **Name**, then
 * **Make the link** and the link to copy (ADR-0074, D18).
 *
 * The products come from the API (the synced catalogue's, with a page of their
 * own); a long catalogue is searched by typing. The link is made by the API from
 * the product's page, never from anything typed here (ADR-0074 §3).
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { Check, ChevronDown, Copy } from "lucide-react";
import { findLinkProducts, makeLink } from "@/lib/api";
import {
  OWN_PLACES,
  PLACE_NAME,
  bare,
  copyText,
  type ChooserProduct,
  type OwnLink,
  type Place,
} from "@/lib/links";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const MAX_NAME = 60;

export function MakeLink({ tenantId, back }: { tenantId: string; back: string }) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{ products: ChooserProduct[]; more: boolean } | null>(null);
  const [searchable, setSearchable] = useState(false);
  const [productId, setProductId] = useState("");
  const [place, setPlace] = useState<Place>("facebook");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<OwnLink | null>(null);
  const [copied, setCopied] = useState<"" | "yes" | "no">("");
  const [error, setError] = useState("");

  // The chooser: read once, then again as the owner types (a long catalogue).
  useEffect(() => {
    let current = true;
    const id = window.setTimeout(
      () => {
        findLinkProducts(tenantId, query)
          .then((result) => {
            if (!current) return;
            setFound(result);
            if (result.more) setSearchable(true);
            setProductId((was) =>
              result.products.some((p) => p.product_id === was)
                ? was
                : (result.products[0]?.product_id ?? ""),
            );
          })
          .catch((caught) => {
            if (current) setError(caught instanceof Error ? caught.message : "Could not load.");
          });
      },
      query ? 250 : 0,
    );
    return () => {
      current = false;
      window.clearTimeout(id);
    };
  }, [tenantId, query]);

  async function make() {
    setBusy(true);
    setError("");
    try {
      setMade(await makeLink(tenantId, { product_id: productId, place, name: name.trim() }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const products = found?.products ?? [];
  const ready = Boolean(productId && name.trim()) && !busy;

  return (
    <div className="max-w-2xl space-y-5 rounded-xl border p-4 sm:p-6" data-make-link-form>
      <div className="space-y-2">
        <label htmlFor="link-product" className="text-sm font-medium">
          Product
        </label>
        {searchable ? (
          <Input
            aria-label="Find a product"
            placeholder="Type to find a product"
            className="h-11 sm:h-10"
            value={query}
            data-link-search
            onChange={(event) => setQuery(event.target.value)}
          />
        ) : null}
        <span className="relative block">
          <select
            id="link-product"
            data-link-product
            value={productId}
            disabled={!products.length || made !== null}
            onChange={(event) => setProductId(event.target.value)}
            className="h-11 w-full appearance-none rounded-lg border border-input bg-background py-0 pr-10 pl-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60 sm:h-10"
          >
            {products.length ? null : (
              <option value="">{found ? "No product found" : "Loading your products…"}</option>
            )}
            {products.map((product) => (
              <option key={product.product_id} value={product.product_id}>
                {product.title ?? product.product_id}
              </option>
            ))}
          </select>
          <ChevronDown
            className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
        </span>
        <p className="text-[13px] text-muted-foreground">
          Any product in your shop. The link opens its page.
          {found?.more && !query ? " Type above to find one not listed." : null}
        </p>
      </div>

      <fieldset className="space-y-2" disabled={made !== null}>
        <legend className="mb-2 text-sm font-medium">Where you&apos;ll post it</legend>
        <div className="flex flex-wrap gap-2">
          {OWN_PLACES.map((option) => (
            <Button
              key={option}
              type="button"
              variant={place === option ? "default" : "outline"}
              aria-pressed={place === option}
              data-link-place={option}
              className="h-11 px-4 sm:h-10"
              onClick={() => setPlace(option)}
            >
              {PLACE_NAME[option]}
            </Button>
          ))}
        </div>
      </fieldset>

      <div className="space-y-2">
        <label htmlFor="link-name" className="text-sm font-medium">
          Name
        </label>
        <Input
          id="link-name"
          className="h-11 sm:h-10"
          value={name}
          maxLength={MAX_NAME}
          placeholder="e.g. Tuesday post"
          disabled={made !== null}
          data-link-name
          onChange={(event) => setName(event.target.value)}
        />
        <p className="text-[13px] text-muted-foreground">
          So you know it later. Shoppers don&apos;t see it.
        </p>
      </div>

      {made ? (
        <div
          role="status"
          data-link-made
          className="space-y-3 rounded-lg border bg-muted/40 px-4 py-4 sm:px-5"
        >
          <p className="text-sm font-semibold">Your link</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
            <span className="rounded-lg border bg-background px-3 py-2 font-mono text-sm break-all select-all">
              {bare(made.link)}
            </span>
            <Button
              className="h-11 self-start px-4 sm:h-10 sm:self-auto"
              data-copy-made-link
              onClick={async () => setCopied((await copyText(made.link)) ? "yes" : "no")}
            >
              {copied === "yes" ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied === "yes" ? "Copied" : "Copy"}
            </Button>
          </div>
          <p className="text-[13px] text-muted-foreground">
            It opens {made.product_title ?? "your product"} on your shop. Its clicks show on Links.
          </p>
          {copied === "no" ? (
            <p className="text-sm text-muted-foreground">
              Your browser did not let us copy it. Select the link and copy it yourself.
            </p>
          ) : null}
          <Link
            href={back}
            className="inline-flex min-h-10 items-center text-sm font-medium underline underline-offset-3"
          >
            Back to Links
          </Link>
        </div>
      ) : (
        <Button className="h-11 px-4 sm:h-10" disabled={!ready} data-make-the-link onClick={make}>
          {busy ? "Making…" : "Make the link"}
        </Button>
      )}

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
