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

import type { Verdict } from "@/lib/review";

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
  /**
   * One line of the shopper's first message, as stored — tokens included. On
   * list rows only; `null` when the shopper never wrote, which the screen says
   * in words rather than leaving a blank line.
   */
  first_question?: string | null;
  /**
   * Whether a handed-over shopper waits for the shop's answer, and how the shop
   * can reach them (ADR-0062). On list rows only while they wait; `null` once
   * answered or for a chat nobody waits on. **Never the address.**
   */
  waiting?: { reach: WaitingReach; since: string } | null;
};

/** How the shop can reach a waiting shopper: an address they typed, or their
 *  account with the shop (signed in). */
export type WaitingReach = "email" | "customer";

/** A transcript's waiting state, and who answered once someone did. */
export type Waiting = {
  reach: WaitingReach;
  since: string;
  answered_at: string | null;
  answered_by: { name: string; role: string | null } | null;
};

/**
 * What *Answer by email* needs (`…/waiting`, behind `shop:handovers:write`): the
 * address, or the customer to find in the shop's own admin when the shop could
 * not give it, and the email the team member's own app is filled with.
 */
export type WaitingDetails = {
  reach: WaitingReach;
  since: string;
  email: string | null;
  customer_id: string | null;
  subject: string;
  body: string;
};

/** The list's own choice for *Waiting for an answer* (ADR-0062 §6). Not a
 *  conversation state: it asks the API for `?waiting=1`. */
export const WAITING_FILTER = "waiting";

export type TranscriptMessage = {
  id: string;
  role: "shopper" | "agent";
  content: string;
  sequence: number;
  intent: string | null;
  /** Present on the agent's message, `null` on the shopper's. */
  state: ConversationState | null;
  /**
   * What the reply looked at. `name` is the synced catalogue's title for a
   * product, category or policy; `null` for a lookup (`type: "tool"`) and for
   * anything the synced catalogue does not hold.
   */
  citations: { type: string; id: string; name: string | null }[];
  /**
   * Which service wrote this message (ADR-0031 §5).
   *
   * `null` on the shopper's own message, and on anything stored before a
   * message could say — so it is rendered where it exists rather than filled
   * in from the conversation, which would be a guess dressed as a record.
   *
   * The conversation carries an `agent_key` too, and it is a different fact:
   * that one is the service the thread *started* with. A dispatched
   * conversation can change service mid-thread, which is exactly what makes
   * this column worth reading.
   */
  agent: string | null;
  created_at: string | null;
};

/**
 * A reply the assistant wrote in practice mode, which no shopper saw.
 *
 * Kept **beside** the thread and never in it, the same separation the API keeps
 * (`console_conversations.py`): `messages` is what a shopper read. Shown under
 * the question it answers (`message_id`), with a link to grade it in Review.
 */
export type HeldReply = {
  /** The Review id — `?turn=` opens exactly this reply there. */
  id: string;
  /** The shopper message this draft answers. */
  message_id: string;
  agent: string;
  /** What it would have done: the same values as a reply's `state`. */
  state: string;
  /** May be empty — see `no_draft_reason`. */
  draft: string;
  /** Non-empty whenever `draft` is empty (ADR-0020). */
  no_draft_reason: string;
  verdict: Verdict | null;
  /** A user id; compared with the reader's own, never shown. */
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
};

export type Transcript = Omit<ConversationRow, "waiting"> & {
  messages: TranscriptMessage[];
  /** How a handed-over shopper can be reached, and who answered (ADR-0062). */
  waiting: Waiting | null;
  /** Oldest first. Empty for a chat that was never held. */
  held: HeldReply[];
  /** The thread hit the server's message bound. Shown, so a cut thread does not
   *  look like a thread that ended. */
  truncated: boolean;
};

/**
 * What each state means to the person reading it, in their terms, not ours.
 *
 * `shadowed` is *"Held for your review"*: it says what happened **and** what the
 * owner does next, where "withheld (shadow mode)" named our mechanism. Approved
 * by the owner with the rest of the 2026-09-27 wording.
 */
export const STATE_LABELS: Record<ConversationState, string> = {
  resolved: "Answered",
  awaiting_customer: "Waiting for the shopper",
  escalated: "Handed to a person",
  blocked: "Blocked as an attack",
  shadowed: "Held for your review",
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

/** What a sent reply did, said after the assistant's name: "NEURA-SELL · answered". */
export const SENT_OUTCOME: Record<ConversationState, string> = {
  resolved: "answered",
  awaiting_customer: "waiting for the shopper",
  escalated: "handed to a person",
  blocked: "blocked as an attack",
  shadowed: "held",
};

/** What a held reply would have done: "NEURA-CARE · would have answered". */
export const HELD_OUTCOME: Record<string, string> = {
  resolved: "would have answered",
  awaiting_customer: "would have asked the shopper for more",
  escalated: "would have handed to a person",
  blocked: "would have been blocked",
};

/**
 * The one sentence at the top of a chat: what the shopper saw, and how many held
 * replies wait for a grade. Counted from the replies on the page, never guessed.
 * `null` when there is no reply of either kind to describe.
 */
export function whatTheShopperSaw(
  held: HeldReply[],
  sent: number,
): { lead: string; rest: string } | null {
  if (held.length === 0) {
    return sent > 0 ? { lead: "Sent.", rest: "The shopper saw every reply below." } : null;
  }

  const seen =
    sent > 0
      ? "The shopper did not see the replies marked Held — they saw the others."
      : held.length === 1
        ? "The shopper did not see the reply below."
        : "The shopper saw none of the replies below.";
  const waiting = held.filter((reply) => reply.verdict === null).length;
  const grade =
    waiting === 0
      ? held.length === 1
        ? "You have graded it."
        : "You have graded all of them."
      : waiting === 1
        ? "1 is waiting for your grade."
        : `${waiting} are waiting for your grade.`;
  return { lead: "Practice mode.", rest: `${seen} ${grade}` };
}

/** The filters offered above the list. `""` is first, so nothing is hidden by default. */
export const STATE_FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  // Who waits for the shop's answer (ADR-0062 §6): right after All, as approved.
  { key: WAITING_FILTER, label: "Waiting for an answer" },
  { key: "shadowed", label: STATE_LABELS.shadowed },
  { key: "escalated", label: STATE_LABELS.escalated },
  { key: "blocked", label: STATE_LABELS.blocked },
  { key: "resolved", label: STATE_LABELS.resolved },
];

/** `1 question`, `19 questions` — a turn, said the way a shop owner counts it. */
export function questions(count: number): string {
  return count === 1 ? "1 question" : `${count} questions`;
}
