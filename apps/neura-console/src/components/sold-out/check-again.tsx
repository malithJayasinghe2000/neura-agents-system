"use client";

/**
 * "Check again" under the Sold out list — a refresh of the page, which asks
 * the shop once more for every product listed. The shop is asked when the
 * owner opens the screen or presses this, and at no other time.
 */
import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CheckAgain() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-10 shrink-0 text-muted-foreground sm:h-9"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      <RefreshCw className={pending ? "animate-spin" : ""} aria-hidden />
      {pending ? "Asking your shop…" : "Check again"}
    </Button>
  );
}
