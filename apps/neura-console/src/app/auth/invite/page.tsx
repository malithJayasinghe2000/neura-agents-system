/**
 * Where an invite link lands (ADR-0058 §4). Built like the sign-in link's page
 * (`auth/verify`): a client component, because the response may set the session
 * cookie, and that cookie has to be stored by the browser making the request.
 */
import { Suspense } from "react";
import { AcceptInvite } from "@/components/accept-invite";

export default function InvitePage() {
  return (
    <main className="grid min-h-dvh place-items-center px-6 py-16">
      <Suspense fallback={<p className="text-sm text-muted-foreground">Opening your invite…</p>}>
        <AcceptInvite />
      </Suspense>
    </main>
  );
}
