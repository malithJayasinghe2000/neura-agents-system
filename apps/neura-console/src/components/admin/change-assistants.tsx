"use client";

/**
 * An approved shop's assistants, changed by FiveNeurals (ADR-0080).
 *
 * The same tick list as Approve, with the shop's own ticked, and **Save**. An
 * added assistant starts at once; a removed one stops and keeps what it made.
 * At least one stays ticked. Save is off until something changed. After a save
 * the page is re-read, so the facts and the switches below follow the new list;
 * the result line says whether the Owners were emailed, never claiming it was.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AssistantChoices } from "@/components/admin/assistant-choices";
import { setAssistants } from "@/lib/api";
import { assistantName, inReadingOrder } from "@/lib/assistants";
import { Button } from "@/components/ui/button";

export function ChangeAssistants({
  tenantId,
  owners,
  current,
  offered,
}: {
  tenantId: string;
  owners: string[];
  /** The shop's assistants now, as keys. */
  current: string[];
  /** Every assistant the API discovered, as keys. */
  offered: string[];
}) {
  const router = useRouter();
  // An assistant the shop has but the API no longer offers still shows, ticked,
  // so saving never drops it unseen.
  const choices = inReadingOrder([...offered, ...current]);
  const [picked, setPicked] = useState(() => new Set(current));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const owner = owners.join(", ") || "its owner";
  const same = picked.size === current.length && current.every((key) => picked.has(key));

  async function save() {
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const done = await setAssistants(tenantId, [...picked]);
      const named = inReadingOrder(done.assistants).map(assistantName).join(" and ");
      setSaved(
        done.emailed
          ? `Saved. It now has ${named}. We emailed ${owner}.`
          : `Saved. It now has ${named}. We couldn't email ${owner}, so tell them yourself.`,
      );
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="assistants-title" className="space-y-3.5" data-change-assistants>
      <div className="space-y-1.5">
        <h2 id="assistants-title" className="text-lg font-semibold">
          Assistants
        </h2>
        <p className="text-sm leading-relaxed text-foreground/80">
          Add or remove this shop&apos;s assistants. One you add starts at once. One you remove
          stops, and keeps what it made, so nothing is lost if you add it back. We email {owner}.
        </p>
      </div>
      <AssistantChoices
        choices={choices}
        picked={picked}
        disabled={busy}
        onChange={(next) => {
          setPicked(next);
          setSaved("");
        }}
      />
      {picked.size === 0 ? (
        <p className="text-sm text-muted-foreground">A shop keeps at least one assistant.</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          className="h-11 px-5 sm:h-10"
          disabled={busy || same || picked.size === 0}
          data-save-assistants
          onClick={save}
        >
          Save
        </Button>
        {saved ? (
          <p className="text-sm text-foreground/80" role="status" data-assistants-saved>
            {saved}
          </p>
        ) : null}
      </div>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
