"use client";

/**
 * *Copy these steps for your developer* — the Help page's steps, the chat box
 * line, the guide for developers and the AI coding tool address as plain text,
 * for an email or a message. The words come from `lib/help.ts`, the same ones
 * the page shows.
 */
import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { stepsAsText } from "@/lib/help";
import { Button } from "@/components/ui/button";

export function CopySteps({
  snippet,
  developerMcpUrl,
}: {
  snippet: string | null;
  developerMcpUrl: string | null;
}) {
  const [copied, setCopied] = useState<"no" | "yes" | "failed">("no");

  function copy() {
    // The clipboard can be refused (an old browser, a page not in focus);
    // saying so beats a button that silently did nothing.
    if (!navigator.clipboard) {
      setCopied("failed");
      return;
    }
    navigator.clipboard
      .writeText(stepsAsText(snippet, developerMcpUrl))
      .then(() => setCopied("yes"))
      .catch(() => setCopied("failed"));
  }

  return (
    // Full width on a phone, under the heading (canvas board 37).
    <span className="flex w-full flex-wrap items-center gap-2 sm:inline-flex sm:w-auto">
      <Button
        variant="outline"
        className="h-11 w-full sm:h-9 sm:w-auto"
        onClick={copy}
        data-copy-steps
      >
        {copied === "yes" ? <Check aria-hidden /> : <Copy aria-hidden />}
        {copied === "yes" ? "Copied" : "Copy these steps for your developer"}
      </Button>
      {copied === "failed" ? (
        <span role="status" className="text-sm text-muted-foreground">
          Couldn&apos;t copy. Select the text on this page instead.
        </span>
      ) : null}
    </span>
  );
}
