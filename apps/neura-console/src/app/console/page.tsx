/**
 * Where a signed-in merchant lands. ADR-0026.
 *
 * Still deliberately small. It lists the shops this person may act for and the
 * one screen that is built — no figures, because `docs/console.md §5` is
 * explicit that a dashboard is where this project's honesty about unmeasured
 * numbers usually dies, and nothing here has been measured.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ClipboardCheck } from "lucide-react";
import { Brand } from "@/components/brand";
import { SignOutButton } from "@/components/sign-out-button";
import { fromApi, hasSession } from "@/lib/server-api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Membership = { tenant_id: string; role: string };
type Me = { signed_in: boolean; memberships?: Membership[] };

export default async function ConsolePage() {
  if (!(await hasSession())) redirect("/");

  // Asked fresh on every load rather than trusted from the cookie. That is the
  // whole reason the cookie carries no tenant: revoking access has to bite on
  // the next request, and a cookie cannot be recalled (ADR-0026 §3).
  const me = await fromApi<Me>("/me");
  if (!me.ok || !me.data.signed_in) redirect("/");

  const memberships: Membership[] = me.data.memberships ?? [];

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
                    <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
                      <div className="space-y-1">
                        <code className="text-sm">{membership.tenant_id}</code>
                        <p className="text-xs uppercase tracking-wide text-muted-foreground">
                          {membership.role}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        // A link wearing a button's clothes — see the same note
                        // on the Review screen's filters.
                        nativeButton={false}
                        render={
                          <Link
                            href={`/console/${encodeURIComponent(membership.tenant_id)}/review`}
                          />
                        }
                      >
                        <ClipboardCheck className="size-3.5" aria-hidden />
                        Review drafts
                      </Button>
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
              Conversations, Shops and Usage are designed and not written. Review is built —
              it&apos;s where you grade what the agent drafted before any shopper sees it.
            </CardDescription>
          </CardHeader>
        </Card>
      </main>
    </div>
  );
}
