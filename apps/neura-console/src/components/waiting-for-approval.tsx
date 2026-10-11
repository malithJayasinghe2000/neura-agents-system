/**
 * The only screen of a shop waiting for approval (ADR-0058 §7, board 44).
 *
 * Shown by the shop's frame instead of the menu and every screen: the API
 * refuses every shop route of a waiting shop (403 `SHOP_WAITING`), so there is
 * nothing else to open. **No time is promised.** *Your shops* appears only for
 * someone with another shop to go back to (R17 a).
 */
import Link from "next/link";
import { Brand } from "@/components/brand";
import { SignOutButton } from "@/components/sign-out-button";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The owner guide on the public website. */
export const OWNER_GUIDE_URL = "https://neura.fiveneurals.com/docs/owners/";

export function WaitingForApproval({
  shop,
  email,
  otherShops,
}: {
  shop: string;
  email: string | null;
  otherShops: boolean;
}) {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-16 sm:px-6">
      <section
        className="flex w-full max-w-[440px] flex-col gap-[18px] rounded-xl border bg-card p-6 text-card-foreground shadow-xs"
        data-waiting-for-approval
      >
        <Brand />
        <div className="space-y-2">
          <h1 className="text-xl font-semibold break-words">{shop} is waiting for approval</h1>
          <p className="text-sm leading-relaxed text-foreground/80">
            Thanks for signing up. FiveNeurals looks at every new shop before its assistant starts.{" "}
            {email ? (
              <>
                We&apos;ll email <strong className="font-semibold break-words">{email}</strong> when
                it&apos;s ready.
              </>
            ) : (
              <>We&apos;ll email you when it&apos;s ready.</>
            )}
          </p>
          <p className="text-sm leading-relaxed text-foreground/80">
            Until then nothing runs and nothing costs anything.
          </p>
        </div>
        <a
          href={OWNER_GUIDE_URL}
          className="text-sm font-medium underline underline-offset-4"
          data-owner-guide
        >
          While you wait: the guide for shop owners
        </a>
        <div className="space-y-3">
          {otherShops ? (
            <Link
              href="/console"
              className={cn(buttonVariants({ variant: "outline" }), "h-10 w-full")}
            >
              Your shops
            </Link>
          ) : null}
          <SignOutButton className="h-10 w-full border-border bg-background text-sm" />
        </div>
      </section>
    </main>
  );
}
