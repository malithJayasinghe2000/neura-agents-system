/**
 * One chat. The "what happened, and why did it say that?" screen.
 *
 * Redesigned 2026-09-28 from the owner's approved mockup (console.md §3.3).
 * Before, a chat held in practice mode showed the shopper's question and a
 * sentence pointing at Review — the reply the assistant wrote was not on the
 * page. Now the chat reads as a chat:
 *
 * - **Every reply sits under the question it answers.** A held reply is drawn
 *   with a dashed edge and *Held — not sent*; a sent one is plain. Held replies
 *   come from the API's `held`, never from `messages` — `messages` is what a
 *   shopper read, and a draft is not.
 * - **Each held reply has its own way to Review** — *Grade this reply*, or the
 *   grade already given and *Open in Review*. One chat with two questions has
 *   two. Grading itself stays in Review, where the evidence sits beside the
 *   buttons (console.md §3.2).
 * - **One sentence at the top** says what the shopper saw and how many replies
 *   wait, counted from the replies on the page.
 * - **What a sent reply looked at, by name** — *Waxed Cotton Field Jacket*, not
 *   `product:1311` — in the words Review uses. The question type
 *   (`order_status`) is no longer shown: the owner agreed it is our word.
 * - **The tokens, explained.** `[EMAIL_1]` unexplained reads as lost data.
 */
import { Fragment, type ReactNode } from "react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Eye, EyeOff, Mail, X } from "lucide-react";
import { LookedAt, type Consulted } from "@/components/conversations/looked-at";
import { Answered, WaitingAnswer } from "@/components/conversations/waiting-answer";
import { WaitingBadge } from "@/components/conversations/waiting-badge";
import { StateBadge } from "@/components/shop/state-badge";
import { TokenNote, hasToken } from "@/components/shop/token-note";
import { When } from "@/components/when";
import { fromApi, hasSession } from "@/lib/server-api";
import { PERMISSION, may, refusal } from "@/lib/roles";
import type { Membership } from "@/lib/shop-assistants";
import { NotAllowed } from "@/components/not-allowed";
import { assistantName } from "@/lib/assistants";
import {
  HELD_OUTCOME,
  SENT_OUTCOME,
  STATE_HELP,
  questions,
  whatTheShopperSaw,
  type HeldReply,
  type Transcript,
  type TranscriptMessage,
  type WaitingDetails,
} from "@/lib/conversations";
import { VERDICT_LABELS, consulted, documentKind, type Verdict } from "@/lib/review";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

type Me = { signed_in: boolean; user_id?: string; memberships?: Membership[] };

/** One line of the chat: something the shopper or the assistant said, or a held draft. */
type Entry = { kind: "message"; message: TranscriptMessage } | { kind: "held"; reply: HeldReply };

export default async function ChatPage({
  params,
}: {
  params: Promise<{ tenantId: string; conversationId: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId, conversationId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.conversations);
  if (refused) return <NotAllowed refusal={refused} what="shoppers' chats" />;
  const shop = encodeURIComponent(tenantId);
  const [result, me] = await Promise.all([
    fromApi<Transcript>(`/shops/${shop}/conversations/${encodeURIComponent(conversationId)}`),
    fromApi<Me>("/me"),
  ]);

  if (!result.ok) {
    return (
      <>
        <BackLink tenantId={tenantId} />
        <Alert variant="destructive">
          <AlertTitle>
            {result.status === 404 ? "No such conversation" : "Could not load the conversation"}
          </AlertTitle>
          <AlertDescription>
            {result.status === 404
              ? "It does not exist, or it belongs to a shop your account cannot act for. Those look the same from here on purpose."
              : result.message}
          </AlertDescription>
        </Alert>
      </>
    );
  }

  const transcript = result.data;
  const viewerId = me.ok ? me.data.user_id : undefined;
  // A handed-over shopper waiting for an answer (ADR-0062 §6). The address is
  // read only for a role that may answer, from its own route.
  const membership = me.ok
    ? me.data.memberships?.find((held) => held.tenant_id === tenantId)
    : undefined;
  const waiting = transcript.waiting;
  const waits = Boolean(waiting && !waiting.answered_at);
  const answers = may(membership, PERMISSION.handovers);
  const details =
    waits && answers
      ? await fromApi<WaitingDetails>(
          `/shops/${shop}/conversations/${encodeURIComponent(conversationId)}/waiting`,
        )
      : null;
  // Where the shopper left their email, as a line in the chat: after the last
  // message written before it. Never the address itself.
  const leftAfter =
    waiting && waiting.reach === "email"
      ? [...transcript.messages]
          .filter((message) => (message.created_at ?? "") <= waiting.since)
          .at(-1)?.id
      : undefined;
  const firstQuestion = transcript.messages.find((message) => message.role === "shopper")?.content;
  const sent = transcript.messages.filter((message) => message.role !== "shopper").length;
  const status = whatTheShopperSaw(transcript.held, sent);
  const entries = thread(transcript);
  const tokenised = hasToken(
    ...transcript.messages.map((message) => message.content),
    ...transcript.held.map((reply) => reply.draft),
  );
  const review = `/console/${shop}/review`;

  return (
    <>
      <BackLink tenantId={tenantId} />

      <header className="space-y-2.5">
        {/* The first question is the title: the same words the owner clicked
            in the list, so they know they are in the right chat. */}
        <h1 className="line-clamp-3 text-2xl font-semibold tracking-tight wrap-break-word">
          {firstQuestion ? `“${firstQuestion.trim()}”` : "A chat with no message from the shopper"}
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {waits ? <WaitingBadge /> : <StateBadge state={transcript.state} />}
          {/* The channel is shown only when it says something: every
              conversation so far came through the website chat. */}
          {transcript.channel !== "web" ? (
            <Badge variant="muted">{transcript.channel}</Badge>
          ) : null}
          <span>
            {questions(transcript.turns)} · started <When iso={transcript.started_at} />
          </span>
        </div>
      </header>

      {waiting && waits && answers ? (
        <WaitingAnswer
          tenantId={tenantId}
          conversationId={conversationId}
          reach={waiting.reach}
          since={waiting.since}
          details={details?.ok ? details.data : null}
        />
      ) : null}
      {waiting?.answered_at ? (
        <Answered
          by={waiting.answered_by?.name ?? ""}
          at={waiting.answered_at}
          typed={waiting.reach === "email"}
        />
      ) : null}

      {status ? (
        <div
          role="note"
          className="flex items-start gap-3 rounded-xl border bg-muted/30 px-4 py-3.5"
        >
          {transcript.held.length > 0 ? (
            <EyeOff className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          ) : (
            <Eye className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          )}
          <p className="text-sm">
            <span className="font-semibold">{status.lead}</span> {status.rest}
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{STATE_HELP[transcript.state]}</p>
      )}

      {entries.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            This conversation has no messages stored. That usually means it was started and nothing
            was ever said in it.
          </CardContent>
        </Card>
      ) : (
        <ol aria-label="The chat" className="space-y-6">
          {entries.map((entry) =>
            entry.kind === "held" ? (
              <HeldItem
                key={entry.reply.id}
                reply={entry.reply}
                review={review}
                viewerId={viewerId}
              />
            ) : (
              <Fragment key={entry.message.id}>
                {entry.message.role === "shopper" ? (
                  <ShopperItem message={entry.message} />
                ) : (
                  <SentItem message={entry.message} />
                )}
                {entry.message.id === leftAfter && waiting ? (
                  <LeftEmail at={waiting.since} />
                ) : null}
              </Fragment>
            ),
          )}
        </ol>
      )}

      {transcript.truncated ? (
        // A thread cut at the bound must not look like a thread that ended.
        <p className="text-xs text-muted-foreground">
          Only the first {transcript.messages.length} messages are shown. This conversation is
          longer than the console displays.
        </p>
      ) : null}

      {tokenised ? <TokenNote /> : null}
    </>
  );
}

/**
 * The chat in reading order: each held draft right after the question it
 * answers. A draft whose question is not on the page — cut by the message bound,
 * or removed since — is still shown, at the end, rather than dropped.
 */
function thread(transcript: Transcript): Entry[] {
  const byQuestion = new Map<string, HeldReply[]>();
  for (const reply of transcript.held) {
    byQuestion.set(reply.message_id, [...(byQuestion.get(reply.message_id) ?? []), reply]);
  }

  const entries: Entry[] = [];
  for (const message of transcript.messages) {
    entries.push({ kind: "message", message });
    for (const reply of byQuestion.get(message.id) ?? []) entries.push({ kind: "held", reply });
    byQuestion.delete(message.id);
  }
  for (const replies of byQuestion.values()) {
    for (const reply of replies) entries.push({ kind: "held", reply });
  }
  return entries;
}

/** Where in the chat the shopper left their email, never the address (ADR-0062). */
function LeftEmail({ at }: { at: string }) {
  return (
    <li className="flex items-center gap-3 text-xs text-muted-foreground" data-left-email>
      <span aria-hidden className="h-px flex-1 bg-border" />
      <span className="inline-flex items-center gap-1.5">
        <Mail className="size-3.5" aria-hidden />
        The shopper left their email for an answer · <When iso={at} time />
      </span>
      <span aria-hidden className="h-px flex-1 bg-border" />
    </li>
  );
}

function BackLink({ tenantId }: { tenantId: string }) {
  return (
    <Button
      size="sm"
      variant="ghost"
      className="-ml-2 h-9"
      nativeButton={false}
      render={<Link href={`/console/${encodeURIComponent(tenantId)}/conversations`} />}
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      All conversations
    </Button>
  );
}

function ShopperItem({ message }: { message: TranscriptMessage }) {
  return (
    <li className="flex flex-col items-start gap-1.5">
      <span className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Shopper</span> ·{" "}
        <When iso={message.created_at} />
      </span>
      <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-muted px-4 py-3 text-sm/relaxed wrap-break-word whitespace-pre-wrap sm:max-w-[78%]">
        {message.content}
      </div>
    </li>
  );
}

function SentItem({ message }: { message: TranscriptMessage }) {
  const tools = message.citations.filter((c) => c.type === "tool").map((c) => c.id);
  const documents = message.citations.filter((c) => c.type !== "tool");
  const sentence = consulted(tools, documents.length);

  return (
    <li className="flex flex-col items-end gap-1.5">
      <ReplyLabel
        chip={<Badge variant="outline">Sent</Badge>}
        agent={message.agent}
        outcome={message.state ? SENT_OUTCOME[message.state] : null}
        at={message.created_at}
      />
      <div className="max-w-[92%] rounded-2xl rounded-tr-sm border bg-background px-4 py-3 text-sm/relaxed wrap-break-word whitespace-pre-wrap sm:max-w-[78%]">
        {message.content}
      </div>
      {sentence ? <LookedAt sentence={sentence} items={documents.map(named)} /> : null}
    </li>
  );
}

function HeldItem({
  reply,
  review,
  viewerId,
}: {
  reply: HeldReply;
  review: string;
  viewerId: string | undefined;
}) {
  return (
    <li className="flex flex-col items-end gap-1.5">
      <ReplyLabel
        chip={<Badge variant="secondary">Held — not sent</Badge>}
        agent={reply.agent}
        outcome={HELD_OUTCOME[reply.state] ?? reply.state}
        at={reply.created_at}
      />
      <div className="max-w-[92%] rounded-2xl rounded-tr-sm border-[1.5px] border-dashed border-muted-foreground/50 bg-background px-4 py-3 text-sm/relaxed wrap-break-word whitespace-pre-wrap sm:max-w-[78%]">
        {reply.draft.trim() ? (
          reply.draft
        ) : (
          <span className="text-muted-foreground italic">
            {reply.no_draft_reason ||
              // ADR-0020: an empty reply with no reason is an error, not a blank.
              "No reply was recorded, and no reason was given — this is a fault worth reporting."}
          </span>
        )}
      </div>

      {reply.verdict ? (
        <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1.5 pt-1">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-sm",
              reply.verdict === "would_have_harmed" && "text-destructive",
            )}
          >
            <VerdictIcon verdict={reply.verdict} />
            <span>
              {grader(reply.reviewed_by, viewerId)}{" "}
              <span className="font-semibold">{VERDICT_LABELS[reply.verdict]}</span>
            </span>
          </span>
          {reply.reviewed_at ? (
            <span className="text-xs text-muted-foreground">
              <When iso={reply.reviewed_at} />
            </span>
          ) : null}
          <Button
            variant="outline"
            className="h-10 px-3.5"
            nativeButton={false}
            render={
              <Link href={`${review}?${new URLSearchParams({ show: "graded", turn: reply.id })}`} />
            }
          >
            Open in Review
          </Button>
        </div>
      ) : (
        <div className="flex w-full flex-col gap-1.5 pt-1 sm:w-auto sm:flex-row sm:items-center sm:gap-3">
          <span className="order-last self-center text-xs text-muted-foreground sm:order-first">
            Waiting for your grade
          </span>
          <Button
            className="h-12 gap-2 px-4 sm:h-11"
            nativeButton={false}
            render={<Link href={`${review}?${new URLSearchParams({ turn: reply.id })}`} />}
          >
            Grade this reply
            <ArrowRight aria-hidden />
          </Button>
        </div>
      )}
    </li>
  );
}

function ReplyLabel({
  chip,
  agent,
  outcome,
  at,
}: {
  chip: ReactNode;
  agent: string | null;
  outcome: string | null;
  at: string | null;
}) {
  return (
    <span className="flex flex-wrap items-center justify-end gap-2 text-xs text-muted-foreground">
      {chip}
      <span>
        {/* Named per reply, because one chat can have two assistants. Null on
            anything stored before a message could say — shown as "Assistant"
            rather than guessed from the conversation. */}
        <span className="font-medium text-foreground">
          {agent ? assistantName(agent) : "Assistant"}
        </span>
        {outcome ? ` · ${outcome}` : ""} · <When iso={at} />
      </span>
    </span>
  );
}

function VerdictIcon({ verdict }: { verdict: Verdict }) {
  if (verdict === "agree") return <Check className="size-4" aria-hidden />;
  if (verdict === "would_have_harmed") return <AlertTriangle className="size-4" aria-hidden />;
  return <X className="size-4" aria-hidden />;
}

/** "You graded this" — the grader is a user id, compared, never shown. */
function grader(reviewedBy: string | null, viewerId: string | undefined): string {
  if (!reviewedBy) return "Graded";
  return reviewedBy === viewerId ? "You graded this" : "Another person graded this";
}

/** A cited source by its catalogue name; by kind and id when the catalogue lacks it. */
function named(citation: TranscriptMessage["citations"][number]): Consulted {
  if (citation.name) {
    return { name: citation.name, note: citation.type === "product" ? "" : `a ${citation.type}` };
  }
  return {
    name: `${documentKind(citation.type)} ${citation.id}`,
    note: "not in your synced catalogue",
  };
}
