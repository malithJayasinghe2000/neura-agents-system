/**
 * What every Links screen may need (console.md §3.15, *Not on the boards*): its
 * name, and the notice for a shop without NEURA-GROW that opened the address.
 */
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export const TITLE = "Links";

/** A shop without NEURA-GROW that opened the address: the menu does not list it. */
export function NotThisShopsLinks() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">{TITLE}</h1>
      <Alert>
        <AlertTitle>{TITLE} is not part of this shop&apos;s plan</AlertTitle>
        <AlertDescription>
          It comes with NEURA-GROW, which this shop doesn&apos;t have.
        </AlertDescription>
      </Alert>
    </>
  );
}
