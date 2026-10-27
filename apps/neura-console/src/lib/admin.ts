/**
 * The FiveNeurals admin's data, as `/v1/admin` sends it (ADR-0061).
 *
 * **Shop facts only, never a shopper**: nothing here can hold a chat, because
 * the API's two database functions cannot return one. The words for each state
 * live here once, so the three screens say the same thing.
 */
import { assistantName } from "@/lib/assistants";

export type Money = { usd: string; measured: boolean };

export type AdminShop = {
  tenant_id: string;
  name: string;
  /** `waiting`, `active`, `suspended` or `offboarding`. */
  status: string;
  /** `practice` or `live`. */
  mode: string;
  assistants: string[];
  website: string | null;
  /** When it signed up, or was made by a command. */
  since: string;
  connected: boolean;
  owners: string[];
  chats_7d: number;
  ai_calls_7d: number;
  cost_7d: Money;
  /** One shop's page only: the features FiveNeurals may switch off (ADR-0065). */
  switches?: AdminSwitch[];
};

/** One feature of one shop that FiveNeurals may switch off (ADR-0065). */
export type AdminSwitch = {
  key: string;
  /** The assistant's key, e.g. `grow`. */
  assistant: string;
  /** The words the agent's manifest gives: a name and what it does. */
  name: string;
  text: string;
  on: boolean;
  /** `null`: never changed, so on. */
  changed_at: string | null;
  changed_by_you: boolean;
};

export type AdminShops = { shops: AdminShop[]; waiting: number };

export type Counts = {
  conversations: number;
  turns: number;
  escalations: number;
  blocked: number;
  llm_calls: number;
  total_tokens: number;
  cost: Money;
};

export type AdminUsage = {
  period: { key: string; days: number; from: string; to: string };
  totals: Counts;
  by_shop: (Counts & { tenant_id: string; name: string | null })[];
  by_assistant: (Counts & { agent_key: string })[];
  shops_without_use: number;
};

/** The API's code for an admin whose sign-in is older than 12 hours (R22). */
export const ADMIN_SIGN_IN_AGAIN = "ADMIN_SIGN_IN_AGAIN";

/** The badge each state wears (board 46). */
export function stateOf(shop: Pick<AdminShop, "status" | "mode">): {
  label: string;
  tone: "waiting" | "practice" | "live" | "stopped";
} {
  if (shop.status === "waiting") return { label: "Waiting for approval", tone: "waiting" };
  if (shop.status === "suspended") return { label: "Suspended", tone: "stopped" };
  if (shop.status === "offboarding") return { label: "Leaving", tone: "stopped" };
  return shop.mode === "practice"
    ? { label: "Practice", tone: "practice" }
    : { label: "Live", tone: "live" };
}

/** *CARE, SELL*: the assistants' short names, for a table cell. */
export function assistantsShort(keys: string[]): string {
  return keys.map((key) => assistantName(key).replace(/^NEURA-/, "")).join(", ");
}

/** *Not priced* when nothing was priced, *No AI use* when nothing ran. Never $0.00. */
export function costWords(cost: Money, calls: number): string {
  if (cost.measured) return money(cost);
  return calls > 0 ? "Not priced" : "No AI use";
}

export function money(cost: Money): string {
  const value = Number(cost.usd);
  return value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(3)}`;
}

export function count(value: number): string {
  return value.toLocaleString("en-US");
}

/** *Oct 11* — or *Oct 11, 2026, 10:42* with the time. */
export function day(iso: string, withTime = false): string {
  const date = new Date(iso);
  return withTime
    ? date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** The website without its `https://`, for a short line. */
export function bareWebsite(website: string | null): string {
  return website ? website.replace(/^https?:\/\//, "") : "";
}
