"use client";

/**
 * The filter row above the Review lists: outcome or grade buttons, each with its
 * count, then *Asked* (a date) and *Assistant*.
 *
 * All of it lives in the address, so a filtered view is a link. The two
 * drop-downs apply the moment they change; *Choose dates…* opens two date boxes
 * and waits for *Apply*, because a range half-typed is not a range. It is a
 * plain GET form underneath, so it still works before the page's JavaScript has
 * loaded — the *Apply* button is then how it is sent.
 */
import Form from "next/form";
import Link from "next/link";
import { useRef, useState } from "react";
import { ASSISTANT_CHOICES } from "@/lib/assistants";
import { ASKED_CHOICES } from "@/lib/days";
import { cn } from "@/lib/utils";

export type Chip = { key: string; label: string; count: number; href: string; current: boolean };

export function FilterBar({
  action,
  keep,
  chips,
  chipsLabel,
  asked,
  from,
  to,
  agent,
}: {
  action: string;
  /** The filters this form does not set, carried through as hidden fields. */
  keep: Record<string, string>;
  chips: Chip[];
  chipsLabel: string;
  asked: string;
  from: string;
  to: string;
  agent: string;
}) {
  const form = useRef<HTMLFormElement>(null);
  const [choice, setChoice] = useState(asked);

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
      <nav aria-label={chipsLabel} className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <Link
            key={chip.key || "all"}
            href={chip.href}
            aria-current={chip.current ? "page" : undefined}
            className={cn(
              "inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors",
              chip.current
                ? "border-foreground bg-foreground text-background"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {chip.label}
            <span className={cn("tabular-nums", chip.current ? "opacity-80" : "opacity-70")}>
              {chip.count}
            </span>
          </Link>
        ))}
      </nav>

      <Form
        ref={form}
        action={action}
        className="flex flex-wrap items-center gap-x-4 gap-y-2 lg:ml-auto"
      >
        {Object.entries(keep).map(([name, value]) =>
          value ? <input key={name} type="hidden" name={name} value={value} /> : null,
        )}
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Asked
          <select
            name="asked"
            value={choice}
            onChange={(event) => {
              setChoice(event.target.value);
              if (event.target.value !== "custom") form.current?.requestSubmit();
            }}
            className="h-9 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {ASKED_CHOICES.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {choice === "custom" ? (
          <>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              From
              <input
                type="date"
                name="from"
                defaultValue={from}
                className="h-9 rounded-lg border border-input bg-background px-2 text-sm text-foreground"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              To
              <input
                type="date"
                name="to"
                defaultValue={to}
                className="h-9 rounded-lg border border-input bg-background px-2 text-sm text-foreground"
              />
            </label>
          </>
        ) : null}
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Assistant
          <select
            name="agent"
            defaultValue={agent}
            onChange={() => form.current?.requestSubmit()}
            className="h-9 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="">All assistants</option>
            {ASSISTANT_CHOICES.map((choice) => (
              <option key={choice.key} value={choice.key}>
                {choice.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className={cn(
            "h-9 rounded-lg border px-3 text-sm font-medium hover:bg-muted",
            // Needed for dates; kept (but quiet) otherwise, for a page whose
            // script has not loaded.
            choice === "custom" ? "" : "sr-only focus:not-sr-only",
          )}
        >
          Apply
        </button>
      </Form>
    </div>
  );
}
