/**
 * Small pieces the three admin screens share (ADR-0061): the state badge, and
 * the two screens an admin route shows instead of itself.
 */
import Link from "next/link";
import { Brand } from "@/components/brand";
import { AdminSignInAgain } from "@/components/admin/admin-sign-in-again";
import { stateOf, type AdminShop } from "@/lib/admin";
import { cn } from "@/lib/utils";

const TONES = {
  waiting: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  practice: "bg-muted text-foreground/80",
  live: "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200",
  stopped: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
} as const;

export function AdminStateBadge({ shop }: { shop: Pick<AdminShop, "status" | "mode"> }) {
  const state = stateOf(shop);
  return (
    <span
      className={cn(
        "inline-block rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[state.tone],
      )}
      data-state={state.tone}
    >
      {state.label}
    </span>
  );
}

/** What someone not on the admin list sees at `/admin`: nothing about it. */
export function NoSuchPage() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-16 sm:px-6">
      <section
        className="flex w-full max-w-sm flex-col gap-4 rounded-xl border bg-card p-6"
        data-no-such-page
      >
        <Brand />
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold">No such page</h1>
          <p className="text-sm text-muted-foreground">There&apos;s nothing at this address.</p>
        </div>
        <Link href="/console" className="text-sm font-medium underline underline-offset-4">
          Your shops
        </Link>
      </section>
    </main>
  );
}

/** An admin whose sign-in is older than 12 hours (R22). */
export function SignInAgain() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-16 sm:px-6">
      <section
        className="flex w-full max-w-sm flex-col gap-4 rounded-xl border bg-card p-6"
        data-admin-sign-in-again
      >
        <Brand />
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold">Sign in again</h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Admin pages need a sign-in from the last 12 hours. Your shops are not affected.
          </p>
        </div>
        <AdminSignInAgain />
      </section>
    </main>
  );
}
