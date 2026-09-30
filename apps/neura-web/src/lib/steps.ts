/**
 * The five connection steps, as the docs show them — the same five, in the same
 * order, as the console's Help page (`apps/neura-console/src/lib/help.ts`) and
 * its Shop connection checklist.
 *
 * **Five, not six.** Product views for NEURA-SELL's *Sold out* are a feature, not
 * a connection step (owner, 2026-09-30); the developer guide explains them in an
 * unnumbered optional section.
 *
 * Step 4 says FiveNeurals makes the chat box key, because that is true today.
 * The owner's direction — the shop owner makes it in the dashboard — is not
 * built and needs its own ADR (ADR-0051 §4).
 */
export type Step = {
  title: string;
  ownerTitle: string;
  body: string;
  short: string;
  check: string;
  who: string;
};

export const STEPS: Step[] = [
  {
    title: "Install or build the bridge",
    ownerTitle: "Your developer installs or builds the bridge",
    short: "The add-on that lets NEURA read your shop.",
    body: "A small add-on that lets NEURA read your products, stock, orders and policy pages. It can't change anything.",
    check: "On Shop connection, press Check now: 'Your shop answers' is ticked",
    who: "Your developer",
  },
  {
    title: "Connect your shop",
    ownerTitle: "FiveNeurals connects your shop",
    short: "We store your shop's address and its secret token.",
    body: "We store your shop's address and its secret token. You never need to see the token.",
    check: "'Your shop is connected' is ticked",
    who: "FiveNeurals",
  },
  {
    title: "Copy your catalogue",
    ownerTitle: "Your catalogue is copied",
    short: "Read once by us. After that, press Sync now when you add products or change stock.",
    body: "We read your products, categories and policy pages once. After that, press Sync now whenever you add products or change stock. Nothing syncs by itself yet.",
    check: "'Your catalogue is copied' is ticked, with the time it was read",
    who: "FiveNeurals, then you",
  },
  {
    title: "Add the chat box",
    ownerTitle: "The chat box goes on your shop",
    short: "One line on your shop's pages, with its public key.",
    body: "FiveNeurals makes the chat box key for your shop's address. Your developer adds one line with it to your pages.",
    check: "'The chat box is on your shop' is ticked once a shopper uses it",
    who: "Your developer",
  },
  {
    title: "Check replies in practice mode",
    ownerTitle: "You check replies in practice mode",
    short: "While practice mode is on, replies are held for you to grade. No shopper sees them.",
    body: "While practice mode is on, your assistant writes replies but no shopper sees them. Grade them in Review, then decide when to go live.",
    check: "Replies appear in Review",
    who: "You",
  },
];

/** Problems an owner meets, in their words. The same five as the console's Help page. */
export const TROUBLE: { seen: string; fix: string }[] = [
  {
    seen: "'Your shop answers' fails",
    fix: "Your shop is down, or the bridge isn't at the address FiveNeurals has. Your developer can check the address opens in a browser.",
  },
  {
    seen: "The chat box doesn't appear",
    fix: "The line isn't on the page, or your shop is showing an old saved copy of its settings. Your developer can clear it.",
  },
  {
    seen: "The chat box appears but won't answer",
    fix: "The key was made for a different address — for example with www. and without. FiveNeurals can make a new one.",
  },
  {
    seen: "A new product or stock change is missing",
    fix: "Our copy is older than the change. Press Sync now on Shop connection.",
  },
  {
    seen: "Sold out stays empty",
    fix: "No data agreement is recorded, or product views are switched off in your shop's settings. 'Is it working?' on Sold out says which.",
  },
];
