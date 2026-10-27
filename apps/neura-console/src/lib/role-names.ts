/** A role's name as people read it (ADR-0058). Safe in the browser: no API call. */
const ROLE_NAMES: Record<string, string> = {
  owner: "Owner",
  support: "Support",
  developer: "Developer",
};

/** *Owner*, *Support*, *Developer*. An unknown role is shown as it is. */
export function roleName(role: string | null | undefined): string {
  return role ? (ROLE_NAMES[role] ?? role) : "";
}
