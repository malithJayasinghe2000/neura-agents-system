"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { signOut } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** `className` lets the side menu lay it out as one of its rows; the behaviour never changes. */
export function SignOutButton({ className }: { className?: string }) {
  const router = useRouter();

  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn("gap-2", className)}
      onClick={async () => {
        // Failure is ignored on purpose: the cookie grants no authority by
        // itself, so the honest response to "sign out did not reach the server"
        // is still to send the person to the signed-out screen.
        await signOut().catch(() => undefined);
        router.replace("/");
        router.refresh();
      }}
    >
      <LogOut aria-hidden />
      Sign out
    </Button>
  );
}
