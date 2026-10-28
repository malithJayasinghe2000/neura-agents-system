"use client";

/**
 * One thing on *Shoppers asked for* (ADR-0068, board 67).
 *
 * **Hide** stores who pressed it; the row turns grey and says the thing leaves
 * the list, and comes back only if shoppers ask for it again after today (R62).
 * The result stays until the owner leaves the page, as *I added it*'s does.
 */
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, EyeOff } from "lucide-react";
import { When } from "@/components/when";
import { hideWanted } from "@/lib/api";
import { askedBy } from "@/lib/gaps";
import { thing, wantedChatsHref, type WantedThing } from "@/lib/wanted";
import { Button } from "@/components/ui/button";

export function WantedRow({ tenantId, item }: { tenantId: string; item: WantedThing }) {
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function hide() {
    setBusy(true);
    setError("");
    try {
      await hideWanted(tenantId, item.label);
      setHidden(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (hidden) {
    return (
      <li
        role="status"
        data-wanted={item.label}
        className="flex items-start gap-3 bg-muted/50 px-4 py-4 sm:px-5"
      >
        <EyeOff className="mt-0.5 size-[18px] shrink-0 text-muted-foreground" aria-hidden />
        <p className="text-sm leading-relaxed">
          <strong className="font-semibold">Hidden.</strong> &ldquo;{thing(item.label)}&rdquo;
          leaves this list. If shoppers ask for it again after today, it comes back here.
        </p>
      </li>
    );
  }

  return (
    <li
      data-wanted={item.label}
      className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-[17px] font-semibold break-words">{thing(item.label)}</p>
        <p className="text-sm break-words text-foreground/80">
          A shopper asked: &ldquo;{item.question}&rdquo;
        </p>
        <p className="text-[13px] text-muted-foreground">
          {askedBy(item.shoppers)} · last on <When iso={item.last_asked} date />
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2 sm:shrink-0">
        <Button
          variant="outline"
          className="h-11 px-4 sm:h-10"
          nativeButton={false}
          data-see-chats
          render={<Link href={wantedChatsHref(tenantId, item.label)} />}
        >
          See the chats
          <ArrowRight aria-hidden />
        </Button>
        <Button
          variant="outline"
          className="h-11 px-4 sm:h-10"
          disabled={busy}
          data-hide
          onClick={hide}
        >
          {busy ? "Hiding…" : "Hide"}
        </Button>
      </div>
    </li>
  );
}
