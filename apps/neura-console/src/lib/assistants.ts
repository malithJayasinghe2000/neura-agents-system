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
 *
 * **Which assistants exist is the API's answer, not this file's** (G136): the
 * Approve screen offers every assistant the API discovered, so one added later
 * is never missing from it. This file only gives them words.
 */
type Assistant = {
  name: string;
  purpose: string;
  /** Whether it chats with shoppers: only these are a "which assistant answered" filter. */
  chats: boolean;
  /** What it does, on the admin's Approve screen. */
  offer: string;
};

const ASSISTANTS: Record<string, Assistant> = {
  care: {
    name: "NEURA-CARE",
    purpose: "Customer care",
    chats: true,
    offer: "Answers shoppers' questions: orders, delivery, returns, the shop's policies.",
  },
  sell: {
    name: "NEURA-SELL",
    purpose: "Shopping help",
    chats: true,
    offer:
      "Helps shoppers choose, and suggests what goes together. Uses some AI in the background for each product.",
  },
  // GROW never chats with a shopper: it works at night and shows the owner what
  // it found (R46: chosen per shop, like SELL).
  grow: {
    name: "NEURA-GROW",
    purpose: "Marketing",
    chats: false,
    offer:
      "Shows the owner what shoppers asked that the shop's pages don't say, and plans a campaign or a greeting for its special dates. Uses some AI each night.",
  },
};

export function assistantName(key: string): string {
  return ASSISTANTS[key]?.name ?? key;
}

/** What it does, in two words — `null` for a key this file does not know. */
export function assistantPurpose(key: string): string | null {
  return ASSISTANTS[key]?.purpose ?? null;
}

/** What it does, for the Approve screen — `null` for a key this file does not know. */
export function assistantOffer(key: string): string | null {
  return ASSISTANTS[key]?.offer ?? null;
}

/**
 * The API's assistants in the order a person reads them: the ones this file
 * knows first, in its order, then any other by its key.
 */
export function inReadingOrder(keys: string[]): string[] {
  const known = Object.keys(ASSISTANTS);
  const rank = (key: string) => (known.includes(key) ? known.indexOf(key) : known.length);
  return [...new Set(keys)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/** The choices for a "which assistant" filter, in the order a person would read them. Chat assistants only. */
export const ASSISTANT_CHOICES: { key: string; label: string }[] = Object.entries(ASSISTANTS)
  .filter(([, { chats }]) => chats)
  .map(([key, { name }]) => ({ key, label: name }));
