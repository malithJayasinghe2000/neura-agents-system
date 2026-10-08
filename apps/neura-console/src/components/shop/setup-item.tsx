/**
 * One line of *Get set up* on Shop connection (console.md §3.4): a tick or not
 * yet, what the step is, and a detail that says when, from where or who does it.
 *
 * Three states, not two, because *not yet* and *it failed* ask different
 * things of the owner: a step nobody has done waits for a person; a shop that
 * did not answer needs fixing. Neither is painted red — nothing here is an
 * alarm, and a checklist of red crosses reads as a broken product on day one.
 */
import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export type SetupState = "done" | "not-yet" | "failed";

export function SetupItem({
  item,
  state,
  title,
  detail,
  action,
  store,
  compact = false,
}: {
  /** What the row is, for the browser check: `connected`, `answers`, `chat-box`… */
  item: string;
  state: SetupState;
  title: string;
  detail?: React.ReactNode;
  action?: React.ReactNode;
  /** The connection a row belongs to, when it belongs to one. */
  store?: string;
  /** The optional rows sit a little tighter, under their own label. */
  compact?: boolean;
}) {
  const Icon = state === "done" ? CheckCircle2 : state === "failed" ? XCircle : CircleDashed;
  return (
    <li
      data-item={item}
      data-step={state}
      data-store={store}
      className={cn(
        "flex flex-wrap items-center gap-x-3.5 gap-y-2 px-4 sm:flex-nowrap sm:px-5",
        compact ? "py-3" : "py-3.5",
      )}
    >
      <Icon
        className={cn(
          "size-5.5 shrink-0",
          state === "done" && "text-muted-foreground",
          state === "not-yet" && "text-muted-foreground/60",
          state === "failed" && "text-foreground",
        )}
        aria-label={state === "done" ? "Done" : state === "failed" ? "Failed" : "Not yet"}
      />
      <span className="min-w-48 flex-1 space-y-0.5 sm:min-w-0">
        <span className={cn("block", state === "done" ? "font-medium" : "font-semibold")}>
          {title}
        </span>
        {detail ? (
          <span className="block text-sm break-words text-muted-foreground">{detail}</span>
        ) : null}
      </span>
      {action ? <span className="ml-9 shrink-0 sm:ml-0">{action}</span> : null}
    </li>
  );
}
