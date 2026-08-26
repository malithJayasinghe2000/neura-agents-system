/**
 * Where a sign-in link lands. ADR-0026.
 *
 * A client component on purpose. The redemption response is what *sets* the
 * session cookie, and that cookie has to be stored by the browser making the
 * request — a server-side redemption would set it on a server's throwaway jar
 * and sign nobody in.
 */
import { Suspense } from "react";
import { VerifyLink } from "@/components/verify-link";

export default function VerifyPage() {
  return (
    <main className="grid min-h-dvh place-items-center px-6 py-16">
      <Suspense fallback={<p className="text-sm text-muted-foreground">Signing you in…</p>}>
        <VerifyLink />
      </Suspense>
    </main>
  );
}
