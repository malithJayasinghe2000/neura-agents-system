/**
 * Each assistant by the name a shop owner knows it by.
 *
 * The API returns an agent's key (`care`, `sell`) and never a display name —
 * `neura-api` may not know one. So the words live here, once, and every screen
 * that shows an assistant asks this file. A key with no entry is shown as
 * itself: an assistant added later must appear under its key rather than
 * disappear from a list.
 */
const ASSISTANTS: Record<string, string> = {
  care: "Customer care",
  sell: "Shopping help",
};

export function assistantName(key: string): string {
  return ASSISTANTS[key] ?? key;
}

/** The choices for a "which assistant" filter, in the order a person would read them. */
export const ASSISTANT_CHOICES: { key: string; label: string }[] = Object.entries(ASSISTANTS).map(
  ([key, label]) => ({ key, label }),
);
