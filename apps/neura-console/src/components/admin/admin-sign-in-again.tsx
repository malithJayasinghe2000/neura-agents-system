"use client";

/** Signs out and opens Sign in, for a fresh link (R22). */
import { useRouter } from "next/navigation";
import { signOut } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function AdminSignInAgain() {
  const router = useRouter();
  return (
    <Button
      className="h-10 w-full"
      onClick={async () => {
        await signOut().catch(() => undefined);
        router.replace("/");
        router.refresh();
      }}
    >
      Sign in again
    </Button>
  );
}
