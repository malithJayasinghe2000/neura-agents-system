/**
 * One shop's frame — the heading and the screen tabs.
 *
 * The tenant id in the URL is **not** authorisation and nothing here treats it
 * as such: this layout only renders it. Every page below calls `acting_for` on
 * the API, which resolves the signed-in person's membership fresh on that
 * request (ADR-0026 §3). A layout renders once and does not re-run when a nested
 * page navigates, so putting the check here would be a check that stops running.
 */
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default async function ShopLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-6 py-8">
      <div className="space-y-2">
        <Link
          href="/console"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          All shops
        </Link>
        <p className="text-xs text-muted-foreground">
          Shop <code className="text-foreground">{tenantId}</code>
        </p>
      </div>
      {children}
    </main>
  );
}
