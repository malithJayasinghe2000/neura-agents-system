/**
 * The frame every console screen sits in. ADR-0026.
 *
 * Four screens were about to repeat the same header, and a wordmark copied four
 * times is a wordmark that ends up different in four places. More importantly,
 * this is where `docs/console.md §5`'s rule about merchant-facing sentences gets
 * its structural half: there is one place a heading or a piece of chrome can be
 * changed, so changing it changes it everywhere.
 *
 * **No data is fetched here.** A layout in Next renders once and is *not*
 * re-rendered when a nested page navigates, so a membership check placed here
 * would be a check that runs on entry and then stops running — which is the
 * opposite of ADR-0026 §3's whole point that access is re-derived per request.
 * Every page below does its own `/me` and its own `acting_for`.
 */
import { Brand } from "@/components/brand";
import { SignOutButton } from "@/components/sign-out-button";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      <header className="border-b">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <Brand />
          <SignOutButton />
        </div>
      </header>
      {children}
    </div>
  );
}
