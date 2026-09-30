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
    title: "Install the NEURA bridge in your shop",
    body: "A small add-on that lets NEURA read your products, stock, orders and policy pages. It cannot change anything.",
    check: "'Your shop answers' is ticked on Shop connection after you press Check now",
    who: "Your developer",
  },
  {
    title: "Connect your shop to NEURA",
    body: "FiveNeurals enters your shop's address and its secret token.",
    check: "'Your shop is connected' is ticked",
    who: "FiveNeurals",
  },
  {
    title: "Copy your catalogue",
    body: "NEURA reads your products, categories and policy pages once. After that, press Sync now whenever you add products or change stock.",
    check: "'Your catalogue is copied' is ticked, with the time it was read",
    who: "FiveNeurals, then you",
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
    seen: "'Your shop answers' fails",
    fix: "Your shop is down, or the bridge isn't installed at the address FiveNeurals has. Your developer can check the address opens in a browser.",
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
