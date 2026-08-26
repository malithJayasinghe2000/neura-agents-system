"use client";

import { useRouter } from "next/navigation";
import { signOut } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function SignOutButton() {
  const router = useRouter();

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={async () => {
        // Failure is ignored on purpose: the cookie grants no authority by
        // itself, so the honest response to "sign out did not reach the server"
        // is still to send the person to the signed-out screen.
        await signOut().catch(() => undefined);
        router.replace("/");
        router.refresh();
      }}
    >
      Sign out
    </Button>
  );
}
