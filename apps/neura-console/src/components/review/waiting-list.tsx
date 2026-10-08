/**
 * The replies waiting for a verdict, grouped the way a person reads them.
 *
 * **By day**, in the reader's own time zone — a heading per day, newest first.
 * **By chat** within a day: replies from one conversation stay together, oldest
 * first, under *"2 replies in one chat"*, because a follow-up question makes no
 * sense read alone. Grading stays one reply at a time; only the showing groups.
 *
 * Every row is a link (`?turn=`), so the open reply is in the address — a link
 * a merchant can send, and the thing the browser's Back button returns to.
 */
import Link from "next/link";
import { MessageSquare } from "lucide-react";
import { When } from "@/components/when";
import { assistantName } from "@/lib/assistants";
import { dayHeading, dayIn } from "@/lib/days";
import type { ReviewTurn } from "@/lib/review";
import { cn } from "@/lib/utils";

export type DayGroup = {
  day: string;
  heading: string;
  chats: { conversation: string; turns: ReviewTurn[] }[];
};

/** Newest-first turns → days → chats. The display order is `flatten()` of this. */
export function groupWaiting(turns: ReviewTurn[], timeZone: string, today: string): DayGroup[] {
  const days: DayGroup[] = [];
  for (const turn of turns) {
    const day = turn.created_at ? dayIn(turn.created_at, timeZone) : "";
    let group = days.find((candidate) => candidate.day === day);
    if (!group) {
      group = { day, heading: day ? dayHeading(day, today) : "Undated", chats: [] };
      days.push(group);
    }
    let chat = group.chats.find((candidate) => candidate.conversation === turn.conversation_id);
    if (!chat) {
      chat = { conversation: turn.conversation_id, turns: [] };
      group.chats.push(chat);
    }
    chat.turns.push(turn);
  }
  for (const group of days) {
    for (const chat of group.chats) chat.turns.reverse(); // oldest first within a chat
  }
  return days;
}

export function flatten(groups: DayGroup[]): ReviewTurn[] {
  return groups.flatMap((group) => group.chats.flatMap((chat) => chat.turns));
}

export function WaitingList({
  groups,
  selectedId,
  hrefFor,
  olderHref,
}: {
  groups: DayGroup[];
  selectedId: string | undefined;
  hrefFor: (turnId: string) => string;
  olderHref: string | null;
}) {
  return (
    <nav aria-label="Replies waiting" className="overflow-hidden rounded-xl border">
      {groups.map((group) => (
        <div key={group.day}>
          <p className="border-b bg-muted/40 px-4 py-2 text-xs font-semibold text-muted-foreground">
            {group.heading}
          </p>
          {group.chats.map((chat) => {
            const together = chat.turns.length > 1;
            return (
              <div key={chat.conversation} className="border-b last:border-b-0">
                {together ? (
                  <p className="flex items-center gap-1.5 px-4 pt-2.5 text-xs text-muted-foreground">
                    <MessageSquare className="size-3.5" aria-hidden />
                    {chat.turns.length} replies in one chat
                  </p>
                ) : null}
                {chat.turns.map((turn) => {
                  const current = turn.id === selectedId;
                  return (
                    <Link
                      key={turn.id}
                      href={hrefFor(turn.id)}
                      aria-current={current ? "true" : undefined}
                      className={cn(
                        "block space-y-1 py-3 pr-4 outline-none transition-colors hover:bg-muted/50 focus-visible:bg-muted/60",
                        together ? "pl-9" : "pl-4",
                        current && "bg-muted",
                      )}
                    >
                      <span
                        className={cn(
                          "block truncate text-sm",
                          current ? "font-semibold" : "font-medium",
                        )}
                      >
                        {turn.question.recorded
                          ? `“${turn.question.text}”`
                          : "Question no longer stored"}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {assistantName(turn.agent)} · <When iso={turn.created_at} time />
                        {turn.escalated ? " · handed to a person" : ""}
                      </span>
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </div>
      ))}
      {olderHref ? (
        <Link
          href={olderHref}
          className="block border-t px-4 py-3 text-center text-sm font-medium hover:bg-muted/50"
        >
          Older replies
        </Link>
      ) : null}
    </nav>
  );
}
