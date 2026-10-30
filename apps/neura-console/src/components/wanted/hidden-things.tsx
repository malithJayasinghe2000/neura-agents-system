"use client";

/**
 * *Hidden* under *Shoppers asked for* (ADR-0070, console.md §3.12).
 *
 * Closed until opened. Lists only what would be on the page if it were not
 * hidden, so **Show again** always brings the thing back; the page is then read
 * again, and the thing moves up into the list.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { When } from "@/components/when";
import { showWantedAgain } from "@/lib/api";
import { askedBy } from "@/lib/gaps";
import { thing, type HiddenThing } from "@/lib/wanted";
import { Button } from "@/components/ui/button";

export function HiddenThings({ tenantId, items }: { tenantId: string; items: HiddenThing[] }) {
  return (
    <details data-hidden-things className="group rounded-xl border">
      <summary className="flex h-12 cursor-pointer items-center px-4 text-sm font-semibold select-none hover:bg-muted/40 sm:px-5">
        Hidden ({items.length})
      </summary>
      <div className="border-t">
        <p className="px-4 pt-3 text-sm leading-relaxed text-muted-foreground sm:px-5">
          Things you hid. Each one comes back by itself if 2 shoppers ask for it again, or press
          Show again.
        </p>
        <ul aria-label="Hidden" className="divide-y">
          {items.map((item) => (
            <HiddenRow key={item.label} tenantId={tenantId} item={item} />
          ))}
        </ul>
      </div>
    </details>
  );
}

function HiddenRow({ tenantId, item }: { tenantId: string; item: HiddenThing }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState("");

  async function showAgain() {
    setBusy(true);
    setError("");
    try {
      await showWantedAgain(tenantId, item.label);
      startTransition(() => router.refresh());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      data-hidden-thing={item.label}
      className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-semibold break-words">{thing(item.label)}</p>
        <p className="text-sm break-words text-foreground/80">
          A shopper asked: &ldquo;{item.question}&rdquo;
        </p>
        <p className="text-[13px] text-muted-foreground">
          {askedBy(item.shoppers)} · hidden on <When iso={item.hidden_at} date />
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      <Button
        variant="outline"
        className="h-11 px-4 sm:h-10 sm:shrink-0"
        disabled={busy || pending}
        data-show-again
        onClick={showAgain}
      >
        {busy || pending ? "Showing…" : "Show again"}
      </Button>
    </li>
  );
}
