/**
 * The sign-in screen. ADR-0026.
 *
 * A server component that decides where you belong: signed in, you go to the
 * console; signed out, you get the form. The decision is made from `/console/me`
 * rather than from anything stored in the browser, because the browser holds no
 * authority — the cookie names a person and the server says what that means.
 */
import { redirect } from "next/navigation";
import { SignInForm } from "@/components/sign-in-form";
import { fromApi, hasSession } from "@/lib/server-api";

export default async function HomePage() {
  // A signed-in visitor belongs in the console. The decision is made from
  // `/console/me` rather than from the cookie's mere presence: the cookie names
  // a person, and only the server says what that person may reach.
  if (await hasSession()) {
    const me = await fromApi<{ signed_in: boolean }>("/me");
    if (me.ok && me.data.signed_in) redirect("/console");
  }

  return (
    <main className="grid min-h-dvh place-items-center px-6 py-16">
      <SignInForm />
    </main>
  );
}
