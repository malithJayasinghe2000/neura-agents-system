/**
 * Whether practice mode is on, said to a role that cannot switch it (R12).
 *
 * The Owner's Home has the switch (`mode-switch.tsx`, ADR-0054); *Go live* is
 * the Owner's alone (ADR-0058 §2). Support and the Developer still need to know
 * the mode, for what they grade and what they test (G86), so they get the same
 * first sentence with no button, and who can change it.
 */
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";

export function ModeLine({
  practice,
  reviewHref,
}: {
  practice: boolean;
  reviewHref: string | null;
}) {
  const Icon = practice ? EyeOff : Eye;
  return (
    <section
      aria-label="Assistant mode"
      data-mode-line
      className="flex items-start gap-3.5 rounded-xl border bg-muted/40 px-4 py-4 sm:px-5"
    >
      <span className="grid size-9 shrink-0 place-items-center rounded-lg border bg-background">
        <Icon className="size-4.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-semibold">
          {practice ? "Practice mode is on" : "Your assistant is live"}
        </p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {practice ? (
            <>
              Your assistant writes a reply to every shopper, but no shopper sees it yet.
              {reviewHref ? (
                <>
                  {" "}
                  Each reply waits in{" "}
                  <Link className="text-foreground underline underline-offset-3" href={reviewHref}>
                    Review
                  </Link>{" "}
                  until it is checked.
                </>
              ) : null}{" "}
              Only the shop&apos;s owner can switch it live.
            </>
          ) : (
            "Shoppers see your assistant's replies as soon as it writes them."
          )}
        </p>
      </div>
    </section>
  );
}
