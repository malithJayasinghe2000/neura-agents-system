"use client";

/**
 * One question on *Missing from your pages* (ADR-0064, board 57).
 *
 * **GROW never writes the answer** (R39, R43): the row says what shoppers asked
 * and where the answer goes, and only the owner can add it, in their own shop.
 * **I added it** stores who pressed it; the row turns green and says the
 * question leaves the list, and comes back only if shoppers ask it again after
 * today. The result stays until the owner leaves the page, as Approve's does.
 */
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { When } from "@/components/when";
import { markGapAdded } from "@/lib/api";
import { askedBy, chatsHref, type GapTopic } from "@/lib/gaps";
import { Button } from "@/components/ui/button";

export function GapRow({
  tenantId,
  productId,
  topic,
}: {
  tenantId: string;
  /** `null`: a question about the shop (*About your shop*). */
  productId: string | null;
  topic: GapTopic;
}) {
  const [added, setAdded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function add() {
    setBusy(true);
    setError("");
    try {
      await markGapAdded(tenantId, productId, topic.fact);
      setAdded(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const key = `${productId ?? ""}|${topic.fact}`;
  if (added) {
    return (
      <li
        role="status"
        data-gap={key}
        className="flex items-start gap-3 bg-green-50 px-4 py-4 sm:px-5 dark:bg-green-950/40"
      >
        <Check
          className="mt-0.5 size-[18px] shrink-0 text-green-800 dark:text-green-300"
          aria-hidden
        />
        <p className="text-sm leading-relaxed">
          <strong className="font-semibold">Marked as added.</strong> &ldquo;{topic.question}&rdquo;
          leaves this list. If shoppers ask it again after today, it comes back here.
        </p>
      </li>
    );
  }

  return (
    <li
      data-gap={key}
      className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-4 sm:px-5"
    >
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-[13px] text-muted-foreground">Shoppers asked</p>
        <p className="font-semibold break-words">&ldquo;{topic.question}&rdquo;</p>
        <p className="text-sm text-foreground/80">
          {productId
            ? "Your page doesn't say. Add the answer to its description in your shop."
            : "Your shop's pages don't say. Add the answer where you explain payment and delivery."}
        </p>
        <p className="text-[13px] text-muted-foreground">
          {askedBy(topic.shoppers)} · last on <When iso={topic.last_asked} date />
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
          render={<Link href={chatsHref(tenantId, productId, topic)} />}
        >
          See the chats
          <ArrowRight aria-hidden />
        </Button>
        <Button className="h-11 px-4 sm:h-10" disabled={busy} data-added onClick={add}>
          <Check aria-hidden />
          {busy ? "Saving…" : "I added it"}
        </Button>
      </div>
    </li>
  );
}
