/**
 * Each assistant by the name a shop owner buys it by.
 *
 * The API returns an agent's key (`care`, `sell`) and never a display name —
 * `neura-api` may not know one. So the words live here, once, and every screen
 * that shows an assistant asks this file. A key with no entry is shown as
 * itself: an assistant added later must appear under its key rather than
 * disappear from a list.
 *
 * **The product's own name, since 2026-09-28** (the owner's decision): the name
 * on what a merchant pays for is the name on every screen — it was *Customer
 * care* / *Shopping help* before. What each one does is kept beside it, for the
 * places with room to say it (`assistantPurpose`), because a name alone does
 * not tell a new owner which assistant answers what.
 */
const ASSISTANTS: Record<string, { name: string; purpose: string }> = {
  care: { name: "NEURA-CARE", purpose: "Customer care" },
  sell: { name: "NEURA-SELL", purpose: "Shopping help" },
};

export function assistantName(key: string): string {
  return ASSISTANTS[key]?.name ?? key;
}

/** What it does, in two words — `null` for a key this file does not know. */
export function assistantPurpose(key: string): string | null {
  return ASSISTANTS[key]?.purpose ?? null;
}

/** The choices for a "which assistant" filter, in the order a person would read them. */
export const ASSISTANT_CHOICES: { key: string; label: string }[] = Object.entries(ASSISTANTS).map(
  ([key, { name }]) => ({ key, label: name }),
);
