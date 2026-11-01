/**
 * Links that count their clicks (NEURA-GROW, ADR-0074; console.md §3.15): what
 * the console's routes return, and the few words the pages build from it.
 *
 * **A click is a tap, not a person** (ADR-0074 §5): the pages say *clicks*,
 * never *visitors* or *people*, and never *sales*.
 */

/** Where the owner posts a link (its `utm_source`). */
export type Place = "facebook" | "instagram" | "whatsapp" | "email" | "other";

/** Which draft of a plan a link belongs to. The banner has none (R112). */
export type Post = "teaser" | "launch" | "last_chance" | "email";

export const PLACE_NAME: Record<Place, string> = {
  facebook: "Facebook",
  instagram: "Instagram",
  whatsapp: "WhatsApp",
  email: "Email",
  other: "Somewhere else",
};

/** A social post has a link per place; the email one (R111). As the API's. */
export const POST_PLACES: Record<Post, Place[]> = {
  teaser: ["facebook", "instagram", "whatsapp"],
  launch: ["facebook", "instagram", "whatsapp"],
  last_chance: ["facebook", "instagram", "whatsapp"],
  email: ["email"],
};

/** *Where you'll post it*, on Make a link (board 82). */
export const OWN_PLACES: Place[] = ["facebook", "instagram", "whatsapp", "email", "other"];

export const POST_NAME: Record<Post, string> = {
  teaser: "Teaser",
  launch: "Launch",
  last_chance: "Last chance",
  email: "Email",
};

/** One post on a plan's page: the product its newest link opens, and its clicks. */
export type PostLink = {
  /** `null`: no link copied yet, so the chooser starts on the plan's first product. */
  product_id: string | null;
  clicks: Partial<Record<Place, number>>;
};

/** `GET …/calendar/plans/{id}`'s `post_links`; `null` for a role without Links. */
export type PostLinks = Record<Post, PostLink> | null;

/** What *Copy … link* gets back. */
export type MadePostLink = {
  id: string;
  link: string;
  post: Post;
  place: Place;
  product_id: string;
  product_title: string | null;
};

export type OwnLink = {
  id: string;
  link: string;
  name: string;
  place: Place;
  product_id: string;
  product_title: string | null;
  clicks: number;
  made_at: string;
};

export type Campaign = {
  date_key: string;
  day: string;
  name: string;
  /** The plan, while it is kept; `null` once deleted 30 days after its date (R116). */
  plan_id: string | null;
  posts: { post: Post; places: Partial<Record<Place, number>>; clicks: number }[];
  clicks: number;
};

export type LinksPage = { own: OwnLink[]; campaigns: Campaign[] };

export type ChooserProduct = { product_id: string; title: string | null };

/**
 * *Facebook 40 · WhatsApp 25 · Instagram 5*, the most first; `null` with none.
 * Places with no click yet are left out, unless every one has none.
 */
export function clicksByPlace(clicks: Partial<Record<Place, number>>): [Place, number][] | null {
  const counted = (Object.entries(clicks) as [Place, number][]).filter(([, n]) => n > 0);
  if (!counted.length) return null;
  return counted.sort((a, b) => b[1] - a[1]);
}

/** *1 click*, *32 clicks*. */
export function clicksWord(count: number): string {
  return count === 1 ? "1 click" : `${count.toLocaleString("en")} clicks`;
}

/** The link as people read it: `go.fiveneurals.com/k7m2qa`, without `https://`. */
export function bare(link: string): string {
  return link.replace(/^https?:\/\//, "");
}

/**
 * Copy a link that is still being made. Safari lets a page write to the
 * clipboard only during the tap, so the text is handed over as a promise the
 * tap starts; a browser without that waits for the link and copies it the
 * ordinary way. `false`: the browser refused.
 */
export async function copyWhenReady(text: Promise<string>): Promise<boolean> {
  if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": text.then((value) => new Blob([value], { type: "text/plain" })),
        }),
      ]);
      return true;
    } catch {
      // Fall through: the plain way, once the link is here.
    }
  }
  return copyText(await text);
}

/** The clipboard, or the older way when a browser refuses it. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const done = document.execCommand("copy");
      area.remove();
      return done;
    } catch {
      return false;
    }
  }
}
