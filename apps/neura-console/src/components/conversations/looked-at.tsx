"use client";

/**
 * Under a sent reply: what it looked at, by the names the shop owner knows —
 * *Waxed Cotton Field Jacket*, not `product:1311`. The first three are shown and
 * the rest are one click away, so a reply that read twelve products does not
 * push the next message off the screen, and nothing is dropped.
 */
import { useState } from "react";

/** How many names show before "Show N more". */
const SHOWN = 3;

export type Consulted = { name: string; note: string };

export function LookedAt({ sentence, items }: { sentence: string; items: Consulted[] }) {
  const [open, setOpen] = useState(false);
  const shown = open ? items : items.slice(0, SHOWN);
  const hidden = items.length - SHOWN;

  return (
    <div className="w-full space-y-2 rounded-xl border bg-muted/30 px-4 py-3 sm:w-[78%]">
      <p className="text-xs text-muted-foreground">What it looked at</p>
      <p className="text-sm">{sentence}</p>
      {items.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-5 text-sm">
          {shown.map((item, index) => (
            <li key={`${item.name}:${index}`}>
              {item.name}
              {item.note ? <span className="text-muted-foreground"> — {item.note}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {hidden > 0 ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="h-8 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          {open ? "Show fewer ▴" : `Show ${hidden} more ▾`}
        </button>
      ) : null}
    </div>
  );
}
