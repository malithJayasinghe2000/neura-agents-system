/**
 * The sign-in screen. ADR-0026.
 *
 * A server component that decides where you belong: signed in, you go to the
 * console; signed out, you get the form. The decision is made from `/console/me`
 * rather than from anything stored in the browser, because the browser holds no
 * authority — the cookie names a person and the server says what that means.
 */
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { SignInForm } from "@/components/sign-in-form";

export default async function HomePage() {
  // Forwarded by hand: a server component's fetch does not carry the browser's
  // cookies unless told to, and the failure is silent — every visitor looks
  // signed out, forever.
  const jar = await cookies();
  const session = jar.get("__Host-fn_session");

  if (session) {
    // Server-to-server, so this one is the API's real address rather than the
  // proxy path: there is no browser here, and therefore no origin to be cross.
  const base = process.env.API_BASE_URL ?? "http://localhost:8010";
    const response = await fetch(`${base}/v1/console/me`, {
      headers: { Cookie: `${session.name}=${session.value}` },
      cache: "no-store",
    }).catch(() => null);

    const body = response?.ok ? await response.json() : null;
    if (body?.data?.signed_in) redirect("/console");
  }

  return (
    <main className="grid min-h-dvh place-items-center px-6 py-16">
      <SignInForm />
    </main>
  );
}
