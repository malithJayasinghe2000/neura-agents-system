/**
 * The shapes the Review screen reads, and the one thing it writes.
 *
 * These mirror `apps/neura-api/src/neura_api/routes/console_review.py` field for
 * field, deliberately without softening anything on the way through. Three of
 * them look like they could be simplified and must not be:
 *
 * - `question.recorded` is separate from `question.text` so the screen can tell
 *   *"the transcript no longer holds this"* apart from *"the shopper said
 *   nothing"*. Collapsing them to an empty string loses the difference.
 * - `verify.grounded` is `boolean | null`, and `null` means the check did not
 *   run — which is not the same as it having failed. A `boolean` here would
 *   render "not grounded" for turns nothing ever examined.
 * - `cost.measured` exists because zero is ambiguous. A local model costs zero
 *   and an unpriced cloud model records zero (`neura_llm.pricing`), so the
 *   screen must not print "$0.00" as though it were a measurement — see
 *   `docs/console.md §5` and `CLAUDE.md §4`.
 */

/** One thing the draft was checked against. */
export type Evidence = {
  /** `"document"` — showable. `"tool"` — nameable only, by design. */
  kind: "document" | "tool";
  type: string;
  id: string;
  excerpt: string;
  truncated: boolean;
  /** Whether `excerpt` is the evidence itself. False for every tool. */
  available: boolean;
  /** Why there is no text. Non-empty exactly when `available` is false. */
  reason: string;
};

export type Cost = {
  usd: string;
  /**
   * False when the figure is zero and therefore says nothing. The screen shows
   * words in that case, never a currency amount.
   */
  measured: boolean;
};

/** One withheld turn, ready to grade. */
export type ReviewTurn = {
  id: string;
  conversation_id: string;
  agent: string;
  created_at: string | null;
  /** Always true: a row in this queue is a reply no shopper ever saw. */
  withheld: boolean;
  mode: string;
  question: { text: string; recorded: boolean; asked_at: string | null };
  /** What would have been sent. May be empty — see `no_draft_reason`. */
  draft: string;
  /**
   * Why there is nothing to grade, in the merchant's words. Non-empty whenever
   * `draft` is empty. An empty draft with an empty reason is the silence
   * ADR-0020 forbids, and the screen treats it as an error rather than a blank.
   */
  no_draft_reason: string;
  intent: string | null;
  state: string;
  escalated: boolean;
  verify: { grounded: boolean | null; reason: string };
  evidence: Evidence[];
  tools: string[];
  cost: Cost;
  latency_ms: number;
  llm_calls: number;
  tool_calls: number;
  prompt_revision: string | null;
  verdict: Verdict | null;
  note: string;
  /** The user id of whoever graded it. Not a name the browser supplied. */
  reviewed_by: string | null;
  reviewed_at: string | null;
};

/**
 * The three words of `agent-runtime.md §6`, unchanged.
 *
 * Three rather than two: "disagree" covers a reply that was wrong or unhelpful,
 * and `would_have_harmed` is kept separate because one harmful turn in fifty is
 * not "96% agreement", it is a reason not to launch.
 */
export type Verdict = "agree" | "disagree" | "would_have_harmed";

export type Scorecard = {
  recorded: number;
  graded: number;
  ungraded: number;
  verdicts: { agree: number; disagree: number; would_have_harmed: number };
  /** `null` until something is graded. Never 0 — an unreviewed queue has not failed. */
  agreement_rate: number | null;
  /** `null` until something is graded. A boolean, deliberately not a rate. */
  harm_free: boolean | null;
  escalated: number;
  cost: Cost;
  total_latency_ms: number;
};

/**
 * The three buttons, in the words the owner approved on 2026-09-27. The values
 * behind them are unchanged — agree · disagree · would-have-harmed
 * (agent-runtime.md §6) — only what a shop owner reads changed.
 */
export const VERDICT_LABELS: Record<Verdict, string> = {
  agree: "Good — I'd send this",
  disagree: "Not good",
  would_have_harmed: "Harmful",
};

/** The same verdicts as a badge in the graded list. */
export const VERDICT_BADGES: Record<Verdict, string> = {
  agree: "Good",
  disagree: "Not good",
  would_have_harmed: "Harmful",
};

/**
 * Said under the buttons. *Harmful* is kept separate from *Not good* because
 * one harmful reply is a reason not to go live, not a point off a percentage
 * (shadow.py).
 */
export const HARMFUL_MEANS =
  "Harmful means it could have misled a shopper — a wrong order status, an invented refund, a policy more generous than yours.";

/**
 * What the turn would have done — the same words, and the same `state` values,
 * as the Conversations screen. A polite "that's outside what I can help with"
 * is an answer there and an answer here: telling it apart would need the API
 * to know each assistant's own labels, which it must not.
 */
export const OUTCOME_LABELS: Record<string, string> = {
  resolved: "Answered",
  awaiting_customer: "Waiting for the shopper",
  escalated: "Would have handed to a person",
  blocked: "Blocked as an attack",
};

export const OUTCOME_FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "resolved", label: "Answered" },
  { key: "escalated", label: "Handed to a person" },
  { key: "blocked", label: "Blocked as an attack" },
];

export const VERDICT_FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "agree", label: "Good" },
  { key: "disagree", label: "Not good" },
  { key: "would_have_harmed", label: "Harmful" },
];

/** How many turns match, split two ways. Counts only — never a rate. */
export type ReviewCounts = {
  total: number;
  by_state: Record<string, number>;
  by_verdict: Partial<Record<Verdict, number>>;
};

/**
 * A lookup's name in plain words: `get_order_status` → "order status".
 * Mechanical on purpose — a list of friendly names would go stale the day an
 * assistant gains a tool, and a stale name is worse than a literal one.
 */
export function lookupWords(tool: string): string {
  return tool.replace(/^(get|search|find|list|lookup)_/, "").replaceAll("_", " ");
}

/**
 * What a reply consulted, in one sentence — *"It looked up products and read 6
 * items from your shop:"* — or `null` when it consulted nothing, which each
 * screen says in its own words. Shared by Review and the chat page, so one reply
 * is described the same way on both.
 */
export function consulted(tools: string[], documents: number): string | null {
  const parts: string[] = [];
  if (tools.length > 0) parts.push(`looked up ${tools.map(lookupWords).join(" and ")}`);
  if (documents > 0)
    parts.push(`read ${documents} ${documents === 1 ? "item" : "items"} from your shop`);
  return parts.length > 0 ? `It ${parts.join(" and ")}${documents > 0 ? ":" : "."}` : null;
}

/** What a cited document is, said the way a shop owner would. */
export function documentKind(type: string): string {
  const known: Record<string, string> = { product: "Product", policy: "Policy", page: "Page" };
  return known[type] ?? type.charAt(0).toUpperCase() + type.slice(1);
}
