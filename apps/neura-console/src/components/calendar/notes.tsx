/**
 * Notes every Marketing calendar screen may need (console.md §3.14, *Not on the
 * boards, said as the other GROW pages say it*): *Paused*, and the notice for a
 * shop without NEURA-GROW that opened the address.
 */
import { Pause } from "lucide-react";
import { When } from "@/components/when";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export const TITLE = "Marketing calendar";

/** ADR-0072 §5: FiveNeurals switched *The calendar's AI plans* off for the shop. */
export function PausedNote({ since }: { since: string }) {
  return (
    <div
      role="status"
      data-paused
      className="flex max-w-3xl items-start gap-3 rounded-xl border bg-muted/40 px-4 py-4 sm:px-5"
    >
      <Pause className="mt-0.5 size-[18px] shrink-0 text-foreground/80" aria-hidden />
      <div className="space-y-1">
        <p className="text-sm font-semibold">
          Paused since <When iso={since} date />
        </p>
        <p className="text-sm leading-relaxed text-foreground/80">
          FiveNeurals has paused the plans for this shop, so no new plan is made. Your dates and the
          plans already made stay. To turn it back on, ask FiveNeurals.
        </p>
      </div>
    </div>
  );
}

/** A shop without NEURA-GROW that opened the address: the menu does not list it. */
export function NotThisShopsPlan() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">{TITLE}</h1>
      <Alert>
        <AlertTitle>{TITLE} is not part of this shop&apos;s plan</AlertTitle>
        <AlertDescription>
          It comes with NEURA-GROW, which this shop doesn&apos;t have.
        </AlertDescription>
      </Alert>
    </>
  );
}

/** The API could not answer: the same words every console screen uses. */
export function CouldNotLoad({ status, message }: { status: number; message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>
        {status === 404 ? "No such shop, or no access to it" : "Could not load"}
      </AlertTitle>
      <AlertDescription>
        {status === 404 ? "Your account does not hold a live membership for this shop." : message}
      </AlertDescription>
    </Alert>
  );
}
