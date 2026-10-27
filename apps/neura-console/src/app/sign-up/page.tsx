/**
 * Create an account (ADR-0058 §7). Open to anyone, signed in or not: someone
 * who already has an account may sign up a second shop (R15).
 */
import { SignUpForm } from "@/components/sign-up-form";

export default function SignUpPage() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-16 sm:px-6">
      <SignUpForm />
    </main>
  );
}
