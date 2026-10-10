/**
 * People: who can open a shop's dashboard, and what each person can do.
 * ADR-0058 §4, from the owner's approved design (console.md §3.8, boards 38 to 41).
 *
 * **The Owner's alone** (`people:members:write`): who works in a shop is the
 * owner's business, and a list of colleagues' emails is personal data. The menu
 * does not list it for another role; the API refuses it whatever this shows.
 */
import { redirect } from "next/navigation";
import { fromApi, hasSession } from "@/lib/server-api";
import { PERMISSION, membershipOf, refusal } from "@/lib/roles";
import { NotAllowed } from "@/components/not-allowed";
import { PeopleScreen, type PeopleView } from "@/components/people/people-screen";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default async function PeoplePage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.people);
  if (refused) return <NotAllowed refusal={refused} what="People" />;

  const [people, membership] = await Promise.all([
    fromApi<PeopleView>(`/shops/${encodeURIComponent(tenantId)}/people`),
    membershipOf(tenantId),
  ]);
  const shopName = membership?.name ?? tenantId;

  if (!people.ok) {
    return (
      <>
        <h1 className="text-2xl font-semibold tracking-tight">People</h1>
        <Alert variant="destructive">
          <AlertTitle>
            {people.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {people.status === 404
              ? "Your account does not hold a live membership for this shop."
              : people.message}
          </AlertDescription>
        </Alert>
      </>
    );
  }

  return <PeopleScreen tenantId={tenantId} shopName={shopName} view={people.data} />;
}
