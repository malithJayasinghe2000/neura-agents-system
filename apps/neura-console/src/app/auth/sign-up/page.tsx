/**
 * Where a sign-up link lands (ADR-0058 §7).
 *
 * A client component on purpose, as the sign-in link's page is: the response
 * sets the session cookie, and only the browser that made the request keeps it.
 */
import { Suspense } from "react";
import { ConfirmSignUp } from "@/components/confirm-sign-up";

export default function ConfirmSignUpPage() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-16 sm:px-6">
      <Suspense fallback={<p className="text-sm text-muted-foreground">Signing you in…</p>}>
        <ConfirmSignUp />
      </Suspense>
    </main>
  );
}
