/**
 * How a conversation ended, in one badge.
 *
 * Colour carries meaning here and is chosen per state rather than per severity:
 * `blocked` is **not** an error. ADR-0012 decided that a recognised attack ended
 * cheaply is a *good* outcome, and painting it red would teach a merchant to
 * read their best-working defence as a problem to fix.
 */
import type { ConversationState } from "@/lib/conversations";
import { STATE_HELP, STATE_LABELS } from "@/lib/conversations";
import { Badge } from "@/components/ui/badge";

const VARIANT: Record<ConversationState, "default" | "secondary" | "outline" | "muted"> = {
  resolved: "muted",
  awaiting_customer: "outline",
  // The one that costs a person's time. The only state a merchant should feel
  // prompted to act on.
  escalated: "default",
  blocked: "secondary",
  shadowed: "secondary",
};

export function StateBadge({ state }: { state: ConversationState }) {
  return (
    <Badge variant={VARIANT[state]} title={STATE_HELP[state]}>
      {STATE_LABELS[state]}
    </Badge>
  );
}
