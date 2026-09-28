"use client";

/**
 * The category filter. Each option carries the address it leads to, worked out
 * on the server with the rest of the screen's state kept — so choosing one is
 * a plain navigation, and the address says what is being shown.
 */
import { useRouter } from "next/navigation";

export type CategoryOption = { value: string; label: string; href: string };

export function CategorySelect({
  options,
  current,
}: {
  options: CategoryOption[];
  current: string;
}) {
  const router = useRouter();
  return (
    <select
      aria-label="Category"
      value={current}
      onChange={(event) => {
        const chosen = options.find((option) => option.value === event.target.value);
        if (chosen) router.push(chosen.href);
      }}
      className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm"
    >
      {options.map((option) => (
        <option key={option.value || "all"} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
