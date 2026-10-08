"use client";

/**
 * Home's mode section, with the switch (ADR-0054). The owner's decisions,
 * 2026-10-02:
 *
 * - **Go live** may be pressed at any time, after a question that shows what
 *   Review holds, as counts. No threshold: none has been measured (§2).
 * - **Back to practice mode** is one press: it can only withhold (§3).
 *
 * The mode is still said before any figure on Home (console.md §3.5); this
 * only adds the way to change it. After a switch the page is read again, so
 * every sentence on it comes from the server's new answer.
 */
import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, RefreshCw } from "lucide-react";
import { setMode } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** What Review holds, for the question before going live. `null`: not loaded. */
export type ReviewFacts = {
  checked: number;
  good: number;
  notGood: number;
  harmful: number;
  waiting: number;
} | null;

export function ModeSwitch({
  tenantId,
  practice,
  reviewHref,
  facts,
}: {
  tenantId: string;
  practice: boolean;
  reviewHref: string;
  facts: ReviewFacts;
}) {
  const router = useRouter();
  const [refreshing, startTransition] = useTransition();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const Icon = practice ? EyeOff : Eye;
  const working = busy || refreshing;

  function switchTo(mode: "live" | "shadow") {
    setBusy(true);
    setError(null);
    setMode(tenantId, mode)
      .then(() => {
        setAsking(false);
        startTransition(() => router.refresh());
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setBusy(false));
  }

  return (
    <section
      aria-label="Assistant mode"
      className="flex items-start gap-3.5 rounded-xl border bg-muted/40 px-4 py-4 sm:px-5"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-lg border bg-background">
        <Icon className="size-4.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-3">
        <div className="space-y-1">
          <p className="font-semibold">
            {practice ? "Practice mode is on" : "Your assistant is live"}
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {practice ? (
              <>
                Your assistant writes a reply to every shopper, but no shopper sees it yet. Each
                reply waits in{" "}
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

        {practice && asking ? (
          <div
            data-go-live-confirm
            className="space-y-3 rounded-xl border border-foreground bg-background p-3.5"
          >
            <p className="font-semibold">Go live?</p>
            <p className="text-sm leading-relaxed">
              From now on, shoppers see your assistant&apos;s replies as soon as it writes them,
              also in chats that are already open.
            </p>
            <p className="text-sm leading-relaxed">
              <Facts facts={facts} reviewHref={reviewHref} />
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                className="h-11 sm:h-10"
                onClick={() => switchTo("live")}
                disabled={working}
                data-confirm-go-live
              >
                {working ? <RefreshCw className="animate-spin" aria-hidden /> : null}
                Go live
              </Button>
              <Button
                variant="outline"
                className="h-11 sm:h-10"
                onClick={() => setAsking(false)}
                disabled={working}
                data-stay-practice
              >
                Stay in practice mode
              </Button>
            </div>
          </div>
        ) : practice ? (
          <Button
            className="h-11 w-full sm:h-10 sm:w-auto"
            onClick={() => setAsking(true)}
            data-go-live
          >
            Go live
          </Button>
        ) : (
          <Button
            variant="outline"
            className="h-11 w-full sm:h-10 sm:w-auto"
            onClick={() => switchTo("shadow")}
            disabled={working}
            data-back-to-practice
          >
            {working ? <RefreshCw className="animate-spin" aria-hidden /> : null}
            Back to practice mode
          </Button>
        )}

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}

/** Counts only, said as a sentence: the owner decides what they mean (§2). */
function Facts({ facts, reviewHref }: { facts: ReviewFacts; reviewHref: string }) {
  if (facts === null) return <>Your Review numbers couldn&apos;t be loaded just now.</>;
  const replies = (n: number) => (n === 1 ? "1 reply" : `${n} replies`);
  const checked =
    facts.checked === 0
      ? "You haven't checked any replies in Review yet."
      : `You checked ${replies(facts.checked)} in Review: ${facts.good} good, ${facts.notGood} not good, ${facts.harmful} harmful.`;
  return (
    <>
      {checked}
      {facts.waiting > 0 ? (
        <>
          {" "}
          {facts.waiting} {facts.checked > 0 ? "more " : ""}
          {facts.waiting === 1 ? "is" : "are"} waiting in{" "}
          <Link className="underline underline-offset-3" href={reviewHref}>
            Review
          </Link>
          .
        </>
      ) : null}
    </>
  );
}
