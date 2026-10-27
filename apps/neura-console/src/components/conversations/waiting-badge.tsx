/**
 * *Waiting for an answer*: a handed-over shopper the shop can still reach
 * (ADR-0062, console.md §3.10). Amber with a dot, apart from the five states'
 * badges, because it asks a person on the team to do something now.
 */
export function WaitingBadge() {
  return (
    <span
      data-waiting-badge
      className="inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full bg-amber-100 px-2 text-xs font-medium whitespace-nowrap text-amber-900"
    >
      <span aria-hidden className="size-1.5 rounded-full bg-amber-500" />
      Waiting for an answer
    </span>
  );
}
