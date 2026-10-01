/**
 * *Connecting your shop* — the words of the Help page (console.md §3.4, canvas
 * board 22), in one place so the page and *Copy these steps for your
 * developer* cannot say two different things.
 *
 * **Platform-agnostic on purpose** (AGENTS.md rule 1, which the console keeps
 * too): no shop platform's name, settings screen or command appears here. A
 * shop connects by implementing our published specification, and the chat box
 * is the one line the API serves.
 *
 * **No time estimates and no numbers** — nothing about setting a shop up has
 * been measured.
 */

export type Who = "You" | "Your developer" | "FiveNeurals" | "FiveNeurals, then you" | string;

export type HelpStep = { title: string; body: string; check: string; who: Who };

export const STEPS: HelpStep[] = [
  {
    title: "Make your shop token",
    body: "On Shop connection, press Make the token. It is shown once: send it to your developer through a password manager, never in a plain email.",
    check: "Step 1 of 'Connect your shop' is ticked",
    who: "You",
  },
  {
    title: "Build the NEURA bridge in your shop",
    body: "A small add-on that lets NEURA read your products, stock, orders and policy pages. It cannot change anything. Your developer puts the token in its settings and sends you its address.",
    check: "Your developer sends you the bridge's address",
    who: "Your developer",
  },
  {
    title: "Check and connect",
    body: "Type the bridge's address on Shop connection and press Check. When it passes, press Connect: NEURA copies your catalogue. After that, press Sync now whenever you add products or change stock.",
    check: "'Your shop is connected' and 'Your catalogue is copied' are ticked",
    who: "You",
  },
  {
    title: "Add the chat box to your shop",
    body: "One line on your shop's pages (below), with a key that only works from your shop's address.",
    check: "'The chat box is on your shop' is ticked once a shopper uses it",
    who: "Your developer",
  },
  {
    title: "Check replies in practice mode",
    body: "While practice mode is on, your assistant writes replies to shoppers' questions but no shopper sees them. Grade them in Review, then decide when to go live.",
    check: "Replies appear in Review",
    who: "You",
  },
];

/** `sell`: a problem only a shop with NEURA-SELL can have — not listed for one without it. */
export const TROUBLE: { seen: string; fix: string; sell?: true }[] = [
  {
    seen: "The check says your shop refused the token",
    fix: "The token in the bridge's settings is not the one you made. Your developer puts it in again. Lost it? Make a new one on Shop connection.",
  },
  {
    seen: "The check can't reach your shop",
    fix: "The address is wrong, or the bridge isn't online. Your developer can check the address opens in a browser.",
  },
  {
    seen: "The chat box doesn't appear",
    fix: "The line isn't on the page, or your shop is showing an old saved copy of its settings. Your developer can clear it.",
  },
  {
    seen: "The chat box appears but refuses to answer",
    fix: "The key is used from a different address than the one it was made for — for example www. versus no www. FiveNeurals can make a new one.",
  },
  {
    seen: "A new product or stock change is missing",
    fix: "Our copy is older than the change. Press Sync now on Shop connection.",
  },
  {
    seen: "Sold out stays empty",
    sell: true,
    fix: "Either no data agreement is recorded, or product views are switched off in your shop's settings. 'Is it working?' on Sold out says which.",
  },
];

export const TWO_KEYS =
  "Two keys, two directions: the shop token is a secret that lets NEURA read your shop — it stays on your shop's server. The chat box key is public, sits in your pages, and only works from your shop's address.";

/** What *Copy these steps for your developer* puts on the clipboard. */
export function stepsAsText(snippet: string | null): string {
  const steps = STEPS.map(
    (step, i) =>
      `${i + 1}. ${step.title} (${step.who})\n   ${step.body}\n   How you'll know: ${step.check}`,
  ).join("\n\n");
  return [
    "Connecting a shop to NEURA",
    "",
    steps,
    "",
    "The chat box — one line on the shop's pages:",
    snippet ?? "(ask FiveNeurals for the line)",
    "Replace the key in it with the chat box key FiveNeurals gives you.",
    "",
    TWO_KEYS,
  ].join("\n");
}
