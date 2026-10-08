/**
 * What has been graded — a table, because looking back is scanning, not reading.
 *
 * Question · assistant · grade · note · asked · who · when graded. A row opens
 * the reply again (`?turn=`), where the grade can be changed. "Who" is *You* or
 * *Another person*: the API returns a user id, and a raw id means nothing to an
 * owner — nor is a name something this screen may invent.
 */
import Link from "next/link";
import { When } from "@/components/when";
import { assistantName } from "@/lib/assistants";
import { VERDICT_BADGES, type ReviewTurn } from "@/lib/review";
import { cn } from "@/lib/utils";

export function GradedTable({
  turns,
  viewerId,
  hrefFor,
}: {
  turns: ReviewTurn[];
  viewerId: string | undefined;
  hrefFor: (turnId: string) => string;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border">
      <table className="w-full min-w-[46rem] border-collapse text-sm">
        <thead>
          <tr className="bg-muted/40 text-left text-xs text-muted-foreground">
            <th scope="col" className="px-4 py-2.5 font-medium">
              What the shopper asked
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Assistant
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Your grade
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Note
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Asked
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              Graded by
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Graded
            </th>
          </tr>
        </thead>
        <tbody>
          {turns.map((turn) => (
            <tr key={turn.id} className="border-t hover:bg-muted/30">
              <td className="max-w-72 px-4 py-3">
                <Link
                  href={hrefFor(turn.id)}
                  className="block truncate font-medium hover:underline"
                >
                  {turn.question.recorded ? `“${turn.question.text}”` : "Question no longer stored"}
                </Link>
              </td>
              <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                {assistantName(turn.agent)}
              </td>
              <td className="px-3 py-3">
                {turn.verdict ? (
                  <span
                    className={cn(
                      "inline-flex h-6 items-center rounded-md border px-2 text-xs font-semibold whitespace-nowrap",
                      turn.verdict === "disagree" && "border-neutral-700 bg-neutral-700 text-white",
                      turn.verdict === "would_have_harmed" &&
                        "border-red-700 bg-red-700 text-white",
                    )}
                  >
                    {VERDICT_BADGES[turn.verdict]}
                  </span>
                ) : null}
              </td>
              <td className="max-w-48 truncate px-3 py-3 text-muted-foreground">
                {turn.note || "—"}
              </td>
              <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                <When iso={turn.created_at} />
              </td>
              <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                {turn.reviewed_by === viewerId ? "You" : "Another person"}
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                <When iso={turn.reviewed_at} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
