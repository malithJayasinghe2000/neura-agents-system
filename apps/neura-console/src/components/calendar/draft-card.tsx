"use client";

/**
 * One draft text of a plan (board 76): read it, **Edit** it, **Copy** it.
 *
 * **[your offer]** is marked, because the owner fills it in (ADR-0072 §5).
 * **Edit** turns the text into a text box with **Cancel** and **Save**; the
 * owner's words are theirs and are not checked as the AI's are (R102). **Copy**
 * puts the text on the clipboard and reads *Copied*; the email is copied with
 * its subject on the first line.
 */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Check, Copy, Pencil } from "lucide-react";
import { savePlanTexts } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/** Which draft: four are one text, the email is a subject and a body. */
export type DraftKind = "teaser" | "launch" | "last_chance" | "email" | "banner";

export function DraftCard({
  tenantId,
  planId,
  kind,
  title,
  when,
  text,
  subject,
  editable,
}: {
  tenantId: string;
  planId: string;
  kind: DraftKind;
  title: string;
  /** *For Mar 31*, *For your home page, Apr 7 to Apr 13*. */
  when: string;
  /** The text, or the email's body. */
  text: string;
  /** The email's subject. */
  subject?: string;
  editable: boolean;
}) {
  const router = useRouter();
  const [shown, setShown] = useState({ text, subject: subject ?? "" });
  const [draft, setDraft] = useState(shown);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<"" | "yes" | "no">("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (copied !== "yes") return;
    const id = window.setTimeout(() => setCopied(""), 3000);
    return () => window.clearTimeout(id);
  }, [copied]);

  async function save() {
    setBusy(true);
    setError("");
    try {
      const texts =
        kind === "email"
          ? { email_subject: draft.subject, email_body: draft.text }
          : { [kind]: draft.text };
      await savePlanTexts(tenantId, planId, texts);
      setShown(draft);
      setEditing(false);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    const whole = kind === "email" ? `Subject: ${shown.subject}\n\n${shown.text}` : shown.text;
    setCopied((await toClipboard(whole)) ? "yes" : "no");
  }

  return (
    <article data-draft={kind} className="space-y-3 rounded-xl border p-4 sm:p-5">
      <div className="space-y-0.5">
        <h3 className="font-semibold">{title}</h3>
        <p className="text-[13px] text-muted-foreground">{when}</p>
      </div>
      {editing ? (
        <div className="space-y-2.5">
          {kind === "email" ? (
            <Input
              aria-label="The email's subject"
              className="h-10"
              value={draft.subject}
              maxLength={3000}
              data-draft-subject
              onChange={(event) => setDraft({ ...draft, subject: event.target.value })}
            />
          ) : null}
          <Textarea
            aria-label={kind === "email" ? "The email" : title}
            className="min-h-28 text-[15px] leading-relaxed"
            value={draft.text}
            maxLength={3000}
            data-draft-text
            onChange={(event) => setDraft({ ...draft, text: event.target.value })}
          />
        </div>
      ) : (
        <div className="space-y-2 rounded-lg bg-muted/60 px-4 py-3.5 text-[15px] leading-relaxed whitespace-pre-wrap">
          {kind === "email" ? (
            <p className="font-medium">
              Subject: <Offer text={shown.subject} />
            </p>
          ) : null}
          <p data-draft-shown>
            <Offer text={shown.text} />
          </p>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {editing ? (
          <>
            <Button
              variant="outline"
              className="h-11 px-4 sm:h-10"
              disabled={busy}
              onClick={() => {
                setDraft(shown);
                setEditing(false);
                setError("");
              }}
            >
              Cancel
            </Button>
            <Button className="h-11 px-4 sm:h-10" disabled={busy} data-draft-save onClick={save}>
              {busy ? "Saving…" : "Save"}
            </Button>
          </>
        ) : (
          <>
            {editable ? (
              <Button
                variant="outline"
                className="h-11 px-4 sm:h-10"
                data-draft-edit
                onClick={() => {
                  setDraft(shown);
                  setEditing(true);
                  setCopied("");
                }}
              >
                <Pencil aria-hidden />
                Edit
              </Button>
            ) : null}
            <Button className="h-11 px-4 sm:h-10" data-draft-copy onClick={copy}>
              {copied === "yes" ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied === "yes" ? "Copied" : "Copy"}
            </Button>
          </>
        )}
      </div>
      {copied === "no" ? (
        <p role="status" className="text-sm text-muted-foreground">
          Your browser did not let us copy it. Select the text and copy it yourself.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </article>
  );
}

/** The text, with each **[your offer]** marked for the owner to fill in. */
function Offer({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\[your offer\])/i).map((part, index) =>
        index % 2 === 1 ? (
          <mark
            key={index}
            data-your-offer
            className="rounded bg-amber-200 px-1 font-semibold text-amber-950 dark:bg-amber-400/80"
          >
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** The clipboard, or the older way when a browser refuses it. */
async function toClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const done = document.execCommand("copy");
      area.remove();
      return done;
    } catch {
      return false;
    }
  }
}
