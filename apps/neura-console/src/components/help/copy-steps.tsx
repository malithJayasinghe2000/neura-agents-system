"use client";

/**
 * *Copy these steps for your developer* — the Help page's steps and the chat
 * box line as plain text, for an email or a message. The words come from
 * `lib/help.ts`, the same ones the page shows.
 */
import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { stepsAsText } from "@/lib/help";
import { Button } from "@/components/ui/button";

export function CopySteps({ snippet }: { snippet: string | null }) {
  const [copied, setCopied] = useState<"no" | "yes" | "failed">("no");

  function copy() {
    // The clipboard can be refused (an old browser, a page not in focus);
    // saying so beats a button that silently did nothing.
    if (!navigator.clipboard) {
      setCopied("failed");
      return;
    }
    navigator.clipboard
      .writeText(stepsAsText(snippet))
      .then(() => setCopied("yes"))
      .catch(() => setCopied("failed"));
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button variant="outline" className="h-10 sm:h-9" onClick={copy} data-copy-steps>
        {copied === "yes" ? <Check aria-hidden /> : <Copy aria-hidden />}
        {copied === "yes" ? "Copied" : "Copy these steps for your developer"}
      </Button>
      {copied === "failed" ? (
        <span role="status" className="text-sm text-muted-foreground">
          Couldn&apos;t copy — select the text on this page instead.
        </span>
      ) : null}
    </span>
  );
}
