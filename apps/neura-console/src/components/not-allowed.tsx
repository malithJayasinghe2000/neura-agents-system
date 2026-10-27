/**
 * *You can't open this page* (console.md §3.8, board 40): a member whose role
 * does not include a screen, who followed a link or typed its address. The
 * words and the link are the approved design; the API refuses the same request
 * with a 403 whatever this shows.
 */
import Link from "next/link";
import type { Refusal } from "@/lib/roles";

export function NotAllowed({ refusal, what }: { refusal: Refusal; what: string }) {
  return (
    <section
      data-not-allowed
      aria-labelledby="not-allowed"
      className="max-w-xl space-y-2 rounded-xl border px-5 py-5 sm:px-6"
    >
      <h1 id="not-allowed" className="text-lg font-semibold">
        You can&apos;t open this page
      </h1>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Your role in {refusal.shop} is {refusal.role}, which doesn&apos;t include {what}. If you
        need it, ask the shop&apos;s owner.
      </p>
      <Link
        href={refusal.next.href}
        className="inline-flex min-h-11 items-center text-sm font-medium underline-offset-4 hover:underline"
      >
        Go to {refusal.next.label}
      </Link>
    </section>
  );
}
