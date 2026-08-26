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

export const VERDICT_LABELS: Record<Verdict, string> = {
  agree: "I'd have sent this",
  disagree: "Wrong or unhelpful",
  would_have_harmed: "This would have caused harm",
};

/**
 * What each verdict means, in the merchant's terms.
 *
 * Written out on the screen rather than assumed, because the difference between
 * the second and the third is the whole reason there are three. A merchant who
 * files a harmful answer under "wrong" has deleted the only signal that blocks
 * a go-live.
 */
export const VERDICT_HELP: Record<Verdict, string> = {
  agree: "You'd be happy for a shopper to receive this exactly as written.",
  disagree: "Off-key, unhelpful or simply wrong — but nobody would have been hurt by it.",
  would_have_harmed:
    "A wrong order status, an invented refund, a policy stated more generously than yours. Kept separate because one of these is a reason not to go live, not a percentage.",
};
