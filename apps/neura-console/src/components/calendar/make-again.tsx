"use client";

/**
 * *Make it again* (ADR-0072 §5, board 76): asks for a fresh plan, made at once.
 *
 * **When a draft was edited it asks first**: *"Your edits will be replaced. Make
 * it again?"*, because the owner's own words go with the old plan (R102). The
 * page then reads itself again and shows the plan being made.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { makePlanAgain } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function MakeAgain({
  tenantId,
  planId,
  edited = false,
  className,
}: {
  tenantId: string;
  planId: string;
  /** Whether the owner saved their own words over a draft. */
  edited?: boolean;
  className?: string;
}) {
  const router = useRouter();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function again() {
    setBusy(true);
    setError("");
    try {
      await makePlanAgain(tenantId, planId);
      setAsking(false);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={className} data-make-again-area>
      {asking ? (
        <div
          role="alertdialog"
          aria-labelledby={`again-${planId}`}
          className="flex flex-col gap-3 rounded-xl border bg-muted/40 px-4 py-3.5 sm:flex-row sm:items-center"
        >
          <p id={`again-${planId}`} className="text-sm font-medium sm:flex-1">
            Your edits will be replaced. Make it again?
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              className="h-11 px-4 sm:h-10"
              disabled={busy}
              data-confirm-make-again
              onClick={again}
            >
              {busy ? "Asking…" : "Make it again"}
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
        <Button
          variant="outline"
          className="h-11 px-4 sm:h-10"
          disabled={busy}
          data-make-again
          onClick={() => (edited ? setAsking(true) : again())}
        >
          <RefreshCw aria-hidden />
          {busy ? "Asking…" : "Make it again"}
        </Button>
      )}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * While a plan is being made: read the page again every few seconds, so the
 * plan appears when the worker has written it. Stops after two minutes.
 */
export function WhileMaking() {
  const router = useRouter();
  useEffect(() => {
    const started = Date.now();
    const id = window.setInterval(() => {
      if (Date.now() - started > 120_000) window.clearInterval(id);
      else router.refresh();
    }, 4000);
    return () => window.clearInterval(id);
  }, [router]);
  return null;
}
