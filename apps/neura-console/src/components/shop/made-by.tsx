/**
 * *by Nimal Perera (Developer)*, after a secret's date (ADR-0058 §6).
 *
 * The Developer may make the shop's secrets, so the Owner can see who did. The
 * name is the person's own, or their email when they never gave one; the role is
 * theirs now, and left out when they are no longer in the shop. Nothing is shown
 * when nobody was recorded (a secret made before this was kept).
 */
import type { MadeBy } from "@/lib/api";
import { roleName } from "@/lib/role-names";

export function MadeByText({ by }: { by: MadeBy | undefined }) {
  if (!by) return null;
  return (
    <span data-made-by>
      {" "}
      by {by.name}
      {by.role ? ` (${roleName(by.role)})` : ""}
    </span>
  );
}
