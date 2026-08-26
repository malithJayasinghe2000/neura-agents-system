/**
 * Where a signed-in merchant lands. ADR-0026, and deliberately almost empty.
 *
 * Screens 2–5 (Conversations, Review, Shops, Usage) are not built yet, and this
 * page says so in plain words rather than showing disabled buttons or invented
 * numbers. `docs/console.md §5` is explicit that a dashboard is exactly where
 * this project's honesty about unmeasured figures usually dies — so there are no
 * figures here at all until there is something real to show.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Brand } from "@/components/brand";
import { SignOutButton } from "@/components/sign-out-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Membership = { tenant_id: string; role: string };

export default async function ConsolePage() {
  const jar = await cookies();
  const session = jar.get("__Host-fn_session");
  if (!session) redirect("/");

  // Server-to-server, so this one is the API's real address rather than the
  // proxy path: there is no browser here, and therefore no origin to be cross.
  const base = process.env.API_BASE_URL ?? "http://localhost:8010";
  const response = await fetch(`${base}/v1/console/me`, {
    headers: { Cookie: `${session.name}=${session.value}` },
    cache: "no-store",
  }).catch(() => null);

  const body = response?.ok ? await response.json() : null;

  // Asked fresh on every load rather than trusted from the cookie. That is the
  // whole reason the cookie carries no tenant: revoking access has to bite on
  // the next request, and a cookie cannot be recalled (ADR-0026 §3).
  if (!body?.data?.signed_in) redirect("/");

  const memberships: Membership[] = body.data.memberships ?? [];

  return (
    <div className="min-h-dvh">
      <header className="border-b">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <Brand />
          <SignOutButton />
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-8 px-6 py-12">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">Welcome back</h1>
          <p className="text-muted-foreground">
            You&apos;re signed in. Here&apos;s what you can reach.
          </p>
        </div>

        {memberships.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">No shop yet</CardTitle>
              <CardDescription>
                Your account is active, but it isn&apos;t connected to a shop — so there&apos;s
                nothing to show. Ask whoever set this up to grant you access, and this
                page will fill in.
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <section className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Your shops</h2>
            <ul className="space-y-2">
              {memberships.map((membership) => (
                <li key={membership.tenant_id}>
                  <Card>
                    <CardContent className="flex items-center justify-between gap-4 py-4">
                      <code className="text-sm">{membership.tenant_id}</code>
                      <span className="text-xs uppercase tracking-wide text-muted-foreground">
                        {membership.role}
                      </span>
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
          </section>
        )}

        <Card className="border-dashed bg-muted/30">
          <CardHeader>
            <CardTitle className="text-base">Not built yet</CardTitle>
            <CardDescription>
              Conversations, Review, Shops and Usage are designed and not written.
              Review comes next — it&apos;s the screen where you grade what the agent
              drafted before any shopper sees it.
            </CardDescription>
          </CardHeader>
        </Card>
      </main>
    </div>
  );
}
