/**
 * The shapes the Conversations screen reads. Read-only — nothing here writes.
 *
 * Mirrors `apps/neura-api/src/neura_api/routes/console_conversations.py`, and
 * the field worth pausing on is `state`. It is **what the shopper experienced**,
 * not what the agent concluded, and its five values deliberately do not collapse
 * into three:
 *
 * - `blocked` and `escalated` are both refusals and cost wildly different things
 *   — one was recognised and cost nobody anything, the other put a person on it
 *   (ADR-0012). A merchant who cannot tell them apart cannot tell a working
 *   guard from a support queue filling up.
 * - `shadowed` is neither. Nothing was resolved and no person was reached; the
 *   shopper was shown a withheld-turn message and the draft went to Review.
 *   Counting it as `resolved` would inflate the one number this product will
 *   eventually be sold on.
 */

export type ConversationState =
  "resolved" | "awaiting_customer" | "escalated" | "blocked" | "shadowed";

export type ConversationRow = {
  id: string;
  agent: string;
  state: ConversationState;
  external_ref: string | null;
  channel: string;
  locale: string;
  turns: number;
  escalations: number;
  started_at: string | null;
  updated_at: string | null;
};

export type TranscriptMessage = {
  id: string;
  role: "shopper" | "agent";
  content: string;
  sequence: number;
  intent: string | null;
  /** Present on the agent's message, `null` on the shopper's. */
  state: ConversationState | null;
  citations: { type: string; id: string }[];
  created_at: string | null;
};

export type Transcript = ConversationRow & {
  messages: TranscriptMessage[];
  /** The thread hit the server's message bound. Shown, so a cut thread does not
   *  look like a thread that ended. */
  truncated: boolean;
};

/** What each state means to the person reading it, in their terms, not ours. */
export const STATE_LABELS: Record<ConversationState, string> = {
  resolved: "Answered",
  awaiting_customer: "Waiting on the shopper",
  escalated: "Handed to a person",
  blocked: "Blocked as an attack",
  shadowed: "Withheld (shadow mode)",
};

export const STATE_HELP: Record<ConversationState, string> = {
  resolved: "The assistant answered and the shopper was shown the reply.",
  awaiting_customer: "The assistant replied and is waiting for the shopper to say more.",
  escalated: "The assistant stopped and handed this to a person. Somebody has to deal with it.",
  blocked:
    "The guard recognised an attack and ended the turn before the assistant did any work. This one cost you almost nothing — which is the point of blocking rather than escalating.",
  shadowed:
    "The assistant answered in full and the shopper was shown nothing. The draft is in Review, waiting for your verdict.",
};

/** The filters offered above the list. `""` is first, so nothing is hidden by default. */
export const STATE_FILTERS: { key: string; label: string }[] = [
  { key: "", label: "Everything" },
  { key: "escalated", label: "Handed to a person" },
  { key: "blocked", label: "Blocked" },
  { key: "shadowed", label: "Withheld" },
  { key: "resolved", label: "Answered" },
];
