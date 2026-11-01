"use client";

/**
 * **Copy** and **Remove** on one of the owner's own links (board 81).
 *
 * *Remove* asks first (console.md §3.15, *Not on the boards*): its clicks are
 * deleted, and the link keeps opening its product, so a post that has it never
 * breaks (R113).
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Check, Link as LinkIcon } from "lucide-react";
import { removeLink } from "@/lib/api";
import { copyText } from "@/lib/links";
import { Button } from "@/components/ui/button";

export function LinkActions({
  tenantId,
  linkId,
  link,
  name,
}: {
  tenantId: string;
  linkId: string;
  link: string;
  name: string;
}) {
  const router = useRouter();
  const [copied, setCopied] = useState<"" | "yes" | "no">("");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (copied !== "yes") return;
    const id = window.setTimeout(() => setCopied(""), 3000);
    return () => window.clearTimeout(id);
  }, [copied]);

  async function remove() {
    setBusy(true);
    setError("");
    try {
      await removeLink(tenantId, linkId);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
      setBusy(false);
    }
  }

  if (asking) {
    return (
      <div
        role="alertdialog"
        aria-labelledby={`remove-${linkId}`}
        data-remove-asking
        className="flex w-full flex-col gap-3 rounded-xl border bg-muted/40 px-4 py-3.5 sm:flex-row sm:items-center"
      >
        <p id={`remove-${linkId}`} className="text-sm font-medium sm:flex-1">
          Remove this link? Its clicks are deleted. The link keeps opening its product.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            className="h-11 px-4 sm:h-10"
            disabled={busy}
            data-confirm-remove
            onClick={remove}
          >
            {busy ? "Removing…" : "Remove"}
          </Button>
          <Button
            variant="outline"
            className="h-11 px-4 sm:h-10"
            disabled={busy}
            onClick={() => setAsking(false)}
          >
            Cancel
          </Button>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="outline"
        className="h-11 px-4 sm:h-10"
        data-copy-own-link
        aria-label={`Copy the link ${name}`}
        onClick={async () => setCopied((await copyText(link)) ? "yes" : "no")}
      >
        {copied === "yes" ? <Check aria-hidden /> : <LinkIcon aria-hidden />}
        {copied === "yes" ? "Copied" : "Copy"}
      </Button>
      <Button
        variant="ghost"
        className="h-11 px-4 text-muted-foreground sm:h-10"
        data-remove-link
        aria-label={`Remove the link ${name}`}
        onClick={() => setAsking(true)}
      >
        Remove
      </Button>
      {copied === "no" ? (
        <p role="status" className="w-full text-sm text-muted-foreground">
          Your browser did not let us copy it. The link is{" "}
          <span className="font-mono text-[13px] select-all">{link}</span>
        </p>
      ) : null}
    </div>
  );
}
