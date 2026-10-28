/**
 * The FiveNeurals admin's frame (ADR-0061): its side menu and the space beside it.
 *
 * **The API is the lock, not this file.** It asks `/v1/admin/shops` once, for the
 * menu's *waiting* count, and shows what the answer means: *No such page* to
 * someone not on the admin list (404), *Sign in again* to an admin signed in more
 * than 12 hours ago, and the code from the admin's phone (ADR-0067): setting it up,
 * or typing it, before any admin page. Every page below asks the API again for itself, because a
 * layout does not re-run when a nested page navigates.
 */
import { redirect } from "next/navigation";
import { AdminSidebar } from "@/components/admin/admin-sidebar";
import { NoSuchPage, SignInAgain } from "@/components/admin/admin-parts";
import { AdminCodePage, AdminCodeSetupPage } from "@/components/admin/admin-code";
import {
  ADMIN_CODE_NEEDED,
  ADMIN_CODE_SETUP,
  ADMIN_SIGN_IN_AGAIN,
  type AdminShops,
} from "@/lib/admin";
import { fromApi, hasSession } from "@/lib/server-api";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  if (!(await hasSession())) redirect("/");

  const shops = await fromApi<AdminShops>("/shops", "/v1/admin");
  if (!shops.ok) {
    if (shops.status === 404) return <NoSuchPage />;
    if (shops.code === ADMIN_SIGN_IN_AGAIN) return <SignInAgain />;
    // ADR-0067: the code from the admin's phone, before any admin page.
    if (shops.code === ADMIN_CODE_SETUP) return <AdminCodeSetupPage />;
    if (shops.code === ADMIN_CODE_NEEDED) return <AdminCodePage />;
    if (shops.status === 401) redirect("/");
  }

  return (
    <div className="md:flex md:min-h-dvh">
      <AdminSidebar waiting={shops.ok ? shops.data.waiting : null} />
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 md:px-10 md:py-10">
        <div className="mx-auto max-w-6xl space-y-7">{children}</div>
      </main>
    </div>
  );
}
