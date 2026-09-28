"use client";

/**
 * *Sync now* — owner-approved 2026-09-28 (console.md §3.4). The console's third
 * write, and it writes **only our copy**: it queues the sync job that already
 * exists, and pressing it again while one is queued or running is the same
 * sync, not a second.
 *
 * Once asked, it watches for the sync to finish by re-reading this screen's own
 * data — our database, never the shop — and then refreshes the page, so the
 * counts and the time above change by themselves, as the sentence promises. It
 * stops watching after a while rather than polling a stuck job for ever; the
 * sentence still says what is true then.
 */
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { readShop, syncShop } from "@/lib/api";
import type { SyncAsked } from "@/lib/shop";
import { Button } from "@/components/ui/button";

/** How often to look, and how many times, while a sync runs. Not shown anywhere. */
const LOOK_EVERY_MS = 3000;
const LOOKS = 60;

type Phase =
  | { at: "idle" }
  | { at: "asking" }
  /** `since`: when products were last read as the wait began — to tell done from not done. */
  | { at: "waiting"; since: string | null; looks: number }
  | { at: "finished" }
  | { at: "not-finished" }
  | { at: "error"; message: string };

export function SyncNow({
  tenantId,
  storeId,
  asked,
  lastRead,
}: {
  tenantId: string;
  storeId: string;
  /** A sync already queued or running when the page was read. */
  asked: SyncAsked | null;
  /** When products were last read from the shop — `null` if never. */
  lastRead: string | null;
}) {
  const router = useRouter();
  const [refreshing, startTransition] = useTransition();
  const [phase, setPhase] = useState<Phase>(
    asked ? { at: "waiting", since: lastRead, looks: 0 } : { at: "idle" },
  );

  const waiting = phase.at === "waiting";
  const looks = waiting ? phase.looks : 0;
  const since = waiting ? phase.since : null;

  useEffect(() => {
    if (!waiting || looks >= LOOKS) return;
    const timer = setTimeout(() => {
      readShop(tenantId)
        .then((view) => {
          const store = view.stores.find((s) => s.id === storeId);
          if (store?.sync_asked) {
            setPhase({ at: "waiting", since, looks: looks + 1 });
            return;
          }
          const read = store?.syncs.find((s) => s.entity_type === "product")?.completed_at ?? null;
          setPhase({ at: read !== since ? "finished" : "not-finished" });
          startTransition(() => router.refresh());
        })
        .catch(() => setPhase({ at: "waiting", since, looks: looks + 1 }));
    }, LOOK_EVERY_MS);
    return () => clearTimeout(timer);
  }, [waiting, looks, since, tenantId, storeId, router]);

  function press() {
    setPhase({ at: "asking" });
    syncShop(tenantId, storeId)
      .then(() => setPhase({ at: "waiting", since: lastRead, looks: 0 }))
      .catch((error: unknown) =>
        setPhase({
          at: "error",
          message: error instanceof Error ? error.message : "The sync could not be asked for.",
        }),
      );
  }

  // Past the last look the button comes back: pressing it again finds the same
  // job if it is still queued, and a new one if it is not.
  const watching = waiting && looks < LOOKS;
  const busy = phase.at === "asking" || watching || refreshing;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button className="h-11 px-5 sm:h-10" onClick={press} disabled={busy} data-sync-now>
          {busy ? <RefreshCw className="animate-spin" aria-hidden /> : null}
          {phase.at === "asking" ? "Asking…" : watching ? "Syncing…" : "Sync now"}
        </Button>
        <span className="text-sm text-muted-foreground">
          Reads your shop again. Nothing in your shop changes.
        </span>
      </div>
      <SyncLine phase={phase} stillWaiting={waiting && !watching} />
    </div>
  );
}

function SyncLine({ phase, stillWaiting }: { phase: Phase; stillWaiting: boolean }) {
  const text =
    phase.at === "waiting"
      ? stillWaiting
        ? "Asked your shop for a fresh copy, and it hasn't finished yet. Reload this page later to see the new counts."
        : "Asked your shop for a fresh copy. The counts and the time above update when it finishes."
      : phase.at === "finished"
        ? "Finished. The counts and the time above are the fresh copy."
        : phase.at === "not-finished"
          ? "The sync stopped before it finished, so the counts above are from the last time one did. Check that your shop answers, then try again."
          : phase.at === "error"
            ? `Could not ask for a sync: ${phase.message}`
            : null;
  if (!text) return null;
  return (
    <p role="status" data-sync-line className="rounded-xl bg-muted/60 px-3 py-2.5 text-sm">
      {text}
    </p>
  );
}
