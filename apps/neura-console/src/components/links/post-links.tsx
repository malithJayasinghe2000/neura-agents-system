"use client";

/**
 * Under one draft of a plan (board 80): which product the post's link opens,
 * **Copy Facebook link**, **Copy Instagram link**, **Copy WhatsApp link** (the
 * email: **Copy the link**), and the clicks so far (ADR-0074 §6, R110, R111).
 *
 * **The link is made on the first copy** (§2), by the API from the product's
 * page in the catalogue; this component never builds an address. Copying the
 * same post, place and product again gives the same link. Choosing another
 * product makes new links; the old ones, already in posts, keep counting.
 */
import { useEffect, useState } from "react";
import { Check, ChevronDown, Link as LinkIcon } from "lucide-react";
import { makePostLink } from "@/lib/api";
import {
  PLACE_NAME,
  POST_PLACES,
  bare,
  clicksByPlace,
  copyWhenReady,
  type MadePostLink,
  type Place,
  type Post,
  type PostLink,
} from "@/lib/links";
import { Button } from "@/components/ui/button";

export type LinkProduct = { product_id: string; title: string | null; image?: string | null };

export function PostLinks({
  tenantId,
  planId,
  post,
  products,
  current,
}: {
  tenantId: string;
  planId: string;
  post: Post;
  /** The plan's products that have a page in the shop, in the plan's order. */
  products: LinkProduct[];
  current: PostLink | undefined;
}) {
  const start =
    current?.product_id && products.some((p) => p.product_id === current.product_id)
      ? current.product_id
      : (products[0]?.product_id ?? "");
  const [productId, setProductId] = useState(start);
  const [busy, setBusy] = useState<Place | null>(null);
  const [copied, setCopied] = useState<{ place: Place; made: MadePostLink } | null>(null);
  const [shown, setShown] = useState<MadePostLink | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(null), 3000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const email = post === "email";
  const label = email ? "This email’s link opens" : "This post’s link opens";
  const chooserId = `link-product-${post}`;

  if (!products.length) {
    return (
      <div className="border-t pt-3">
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          None of this plan&apos;s products has a page in your shop, so there is no link to copy.
        </p>
      </div>
    );
  }

  async function copy(place: Place) {
    setBusy(place);
    setError("");
    setShown(null);
    const made = makePostLink(tenantId, planId, { post, place, product_id: productId });
    try {
      const done = await copyWhenReady(made.then((m) => m.link));
      const link = await made;
      if (done) {
        setCopied({ place, made: link });
        setShown(link);
      } else {
        setShown(link);
        setError(
          "Your browser did not let us copy it. Select the link above and copy it yourself.",
        );
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  const counted = clicksByPlace(current?.clicks ?? {});
  const title = (id: string) => products.find((p) => p.product_id === id)?.title ?? "this product";
  // G126: which of the shop's own photos goes with the post (never an AI picture, D17).
  const photo = products.find((p) => p.product_id === productId)?.image ?? null;

  return (
    <div data-post-links={post} className="space-y-3 border-t pt-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
        <label htmlFor={chooserId} className="text-sm font-medium">
          {label}
        </label>
        <span className="relative w-full sm:w-auto sm:min-w-72">
          <select
            id={chooserId}
            data-link-product
            value={productId}
            onChange={(event) => {
              setProductId(event.target.value);
              setShown(null);
              setCopied(null);
            }}
            className="h-11 w-full appearance-none rounded-lg border border-input bg-background py-0 pr-10 pl-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 sm:h-10"
          >
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
      </div>

      <div data-post-photo className="flex items-center gap-3">
        {photo ? (
          <>
            {/* The shop's own photo, from the synced catalogue. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={photo}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              className="size-12 shrink-0 rounded-md border bg-muted object-cover"
            />
            <p className="text-sm">
              Post it with this photo.{" "}
              <a
                href={photo}
                target="_blank"
                rel="noreferrer"
                className="font-medium underline underline-offset-3"
              >
                Open the photo
              </a>{" "}
              <span className="text-muted-foreground">to save it.</span>
            </p>
          </>
        ) : (
          <p className="text-[13px] text-muted-foreground">
            No photo of {title(productId)} in your shop yet.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {POST_PLACES[post].map((place) => {
          const done = copied?.place === place;
          return (
            <Button
              key={place}
              variant="outline"
              className="h-11 w-full px-4 sm:h-10 sm:w-auto"
              data-copy-link={place}
              disabled={busy !== null}
              onClick={() => copy(place)}
            >
              {done ? <Check aria-hidden /> : <LinkIcon aria-hidden />}
              {done ? "Copied" : email ? "Copy the link" : `Copy ${PLACE_NAME[place]} link`}
            </Button>
          );
        })}
      </div>

      {shown ? (
        <p
          role="status"
          data-link-copied
          className={
            error
              ? "rounded-lg border px-3.5 py-2.5 text-sm"
              : "flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 px-3.5 py-2.5 text-sm text-green-950 dark:border-green-900 dark:bg-green-950/40 dark:text-green-100"
          }
        >
          {error ? null : (
            <Check
              className="mt-0.5 size-4 shrink-0 text-green-700 dark:text-green-400"
              aria-hidden
            />
          )}
          <span className="min-w-0 break-words">
            {error ? null : "Copied "}
            <span className="font-mono text-[13px] select-all">{bare(shown.link)}</span>. It opens{" "}
            {shown.product_title ?? title(shown.product_id)} on your shop.
          </span>
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <p data-link-clicks className="text-[13px] text-muted-foreground">
        {counted ? (
          <>
            Clicks so far:{" "}
            {email ? (
              <strong className="font-semibold text-foreground">{counted[0][1]}</strong>
            ) : (
              counted.map(([place, count], index) => (
                <span key={place}>
                  {index ? " · " : null}
                  <strong className="font-semibold text-foreground">
                    {PLACE_NAME[place]} {count}
                  </strong>
                </span>
              ))
            )}
          </>
        ) : (
          "No clicks yet."
        )}
      </p>
    </div>
  );
}
