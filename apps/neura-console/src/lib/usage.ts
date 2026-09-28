/**
 * The shapes the Usage screen reads.
 *
 * **There is no rate in this file, and that is the point.** `docs/console.md §5`
 * calls a dashboard the place this project's honesty about unmeasured numbers
 * usually dies, and the specific way it dies is a true counter divided by
 * another true counter and given a business name. Escalations over conversations
 * is arithmetic the data supports; *deflection* is a claim it does not — it says
 * nothing about a shopper who gave up or accepted a wrong answer, and
 * `CLAUDE.md §4` lists deflection rate under **unknown**.
 *
 * So: counts, their period, and `caveats` — sentences written by the server,
 * because a merchant-facing sentence hard-coded into a JavaScript bundle is one
 * nobody reviews and nobody can change (ADR-0020 §3).
 */

export type Cost = {
  usd: string;
  /** False when zero, which says nothing: free local model, or no price set. */
  measured: boolean;
};

export type Totals = {
  conversations: number;
  turns: number;
  escalations: number;
  blocked: number;
  llm_calls: number;
  tool_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost: Cost;
};

/**
 * A sentence the **server** wrote about what the figures do not say. `key` is
 * stable so a screen can show the one that belongs to its figures by name —
 * Home shows counts and no cost, so it asks for `handed_to_a_person` only.
 */
export type Caveat = {
  key:
    "practice_mode" | "cost_not_recorded" | "handed_to_a_person" | "background_ai" | (string & {});
  text: string;
};

export type Usage = {
  period: {
    key: string;
    since: string | null;
    through: string;
    /** `null` means everything recorded — not a number of days. */
    days: number | null;
    /** The first day anything was recorded — where "everything" starts. */
    first_recorded: string | null;
  };
  /** `live` or `shadow`. In shadow, nobody saw any of the work below. */
  mode: string;
  withheld: boolean;
  totals: Totals;
  /**
   * The same period, per assistant (since 2026-09-28; today only before). The
   * meter keeps one row per day per assistant, so these add up to `totals`.
   */
  by_agent: Record<string, Totals>;
  /** Only the ones that are true right now. Never boilerplate. */
  caveats: Caveat[];
};

export const PERIODS: { key: string; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "all", label: "Everything" },
];
