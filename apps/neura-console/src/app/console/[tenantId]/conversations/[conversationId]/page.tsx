/**
 * One transcript. The "why did it say that?" screen.
 *
 * Three things are on the page that a chat log alone would not carry, and each
 * is here because a merchant reading a complaint needs it:
 *
 * - **how each turn ended**, per message, from the same `state` the eval harness
 *   scores — so a reply that reads as a refusal here counts as one there;
 * - **what the reply cited**, which is the difference between a right answer
 *   from the right lookup and a right answer by luck (the same distinction
 *   Review is built around);
 * - **the tokens**, explained. `[EMAIL_1]` unexplained reads as lost data.
 *
 * A shadowed turn shows the shopper's message and no reply, because that is
 * exactly what happened — the draft is in Review, and saying so beats an empty
 * space (ADR-0020).
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { StateBadge } from "@/components/shop/state-badge";
import { TokenNote, hasToken } from "@/components/shop/token-note";
import { When } from "@/components/when";
import { fromApi, hasSession } from "@/lib/server-api";
import { assistantName } from "@/lib/assistants";
import {
  STATE_HELP,
  questions,
  type Transcript,
  type TranscriptMessage,
} from "@/lib/conversations";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default async function TranscriptPage({
  params,
}: {
  params: Promise<{ tenantId: string; conversationId: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId, conversationId } = await params;
  const result = await fromApi<Transcript>(
    `/shops/${encodeURIComponent(tenantId)}/conversations/${encodeURIComponent(conversationId)}`,
  );

  if (!result.ok) {
    return (
      <>
        <Alert variant="destructive">
          <AlertTitle>
            {result.status === 404 ? "No such conversation" : "Could not load the transcript"}
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
  const tokenised = hasToken(...transcript.messages.map((message) => message.content));

  return (
    <>
      <div className="space-y-3">
        <Button
          size="sm"
          variant="ghost"
          nativeButton={false}
          render={<Link href={`/console/${encodeURIComponent(tenantId)}/conversations`} />}
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          All conversations
        </Button>

        <div className="flex flex-wrap items-center gap-2">
          <StateBadge state={transcript.state} />
          <Badge variant="outline">{assistantName(transcript.agent)}</Badge>
          {/* The channel is shown only when it says something: every
              conversation so far came through the website chat. */}
          {transcript.channel !== "web" ? (
            <Badge variant="muted">{transcript.channel}</Badge>
          ) : null}
          <span className="text-xs text-muted-foreground">
            {questions(transcript.turns)} · started <When iso={transcript.started_at} />
          </span>
        </div>

        <p className="text-sm text-muted-foreground">{STATE_HELP[transcript.state]}</p>
      </div>

      {transcript.messages.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            This conversation has no messages stored. That usually means it was started and nothing
            was ever said in it.
          </CardContent>
        </Card>
      ) : (
        <ol className="space-y-3">
          {transcript.messages.map((message) => (
            <li key={message.id}>
              <MessageBubble message={message} />
            </li>
          ))}
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

function MessageBubble({ message }: { message: TranscriptMessage }) {
  const fromShopper = message.role === "shopper";

  return (
    <Card size="sm" className={fromShopper ? "" : "bg-muted/40"}>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">
            {fromShopper ? "Shopper" : "Assistant"}
          </span>
          {/* Which service answered (ADR-0031 §5). A dispatched conversation can
              change service mid-thread — the shopper asks for a jacket, then
              asks where their parcel is — and the merchant reads one thread
              rather than half a story told twice. Rendered only where it
              exists: null on the shopper's message, and on anything stored
              before a message could say. */}
          {message.agent ? <Badge variant="outline">{assistantName(message.agent)}</Badge> : null}
          {message.intent ? <Badge variant="muted">{message.intent}</Badge> : null}
          {/* Per-turn outcome, on the reply. Null on the shopper's message,
              because the question did not have an outcome. */}
          {message.state ? <StateBadge state={message.state} /> : null}
          <span className="ml-auto">
            <When iso={message.created_at} />
          </span>
        </div>

        <p className="text-sm whitespace-pre-wrap">{message.content}</p>

        {message.citations.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5 pt-1">
            <span className="text-xs text-muted-foreground">Answered from</span>
            {message.citations.map((citation, index) => (
              <Badge key={`${citation.type}:${citation.id}:${index}`} variant="outline">
                {citation.type}:{citation.id}
              </Badge>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
