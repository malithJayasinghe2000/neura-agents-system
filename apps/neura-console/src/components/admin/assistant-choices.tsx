"use client";

/**
 * The tick list of assistants, as Approve shows it (ADR-0061 §7) and as
 * *Assistants* on an approved shop shows it (ADR-0080): one card per assistant
 * the API discovered (G136), its name and what it does from `lib/assistants.ts`.
 */
import { assistantName, assistantOffer } from "@/lib/assistants";

export function AssistantChoices({
  choices,
  picked,
  onChange,
  disabled = false,
}: {
  /** Keys, in reading order. */
  choices: string[];
  picked: Set<string>;
  onChange: (next: Set<string>) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-3">
      {choices.map((key) => (
        <label
          key={key}
          className="flex cursor-pointer gap-3 rounded-xl border px-4 py-3.5 has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50"
        >
          <input
            type="checkbox"
            className="mt-0.5 size-[18px] shrink-0 accent-foreground"
            checked={picked.has(key)}
            disabled={disabled}
            data-assistant={key}
            onChange={(event) => {
              const next = new Set(picked);
              if (event.target.checked) next.add(key);
              else next.delete(key);
              onChange(next);
            }}
          />
          <span className="space-y-0.5">
            <span className="block text-sm font-semibold">{assistantName(key)}</span>
            {assistantOffer(key) ? (
              <span className="block text-[13px] leading-snug text-muted-foreground">
                {assistantOffer(key)}
              </span>
            ) : null}
          </span>
        </label>
      ))}
    </div>
  );
}
