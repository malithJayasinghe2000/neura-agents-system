/**
 * Moving between one shop's four screens.
 *
 * Built from a single list so the set of screens is stated once. A screen that
 * is designed and not written appears here as **disabled with a reason**, not as
 * a working link to a 404 and not as a silent absence: `docs/console.md §5` says
 * the empty state is the most valuable documentation in the product, and "this
 * exists and is not built yet" is an empty state like any other.
 */
import Link from "next/link";
import { cn } from "@/lib/utils";

export type ShopScreen = "conversations" | "review" | "shops" | "usage";

const SCREENS: { key: ShopScreen; label: string; built: boolean }[] = [
  { key: "conversations", label: "Conversations", built: true },
  { key: "review", label: "Review", built: true },
  { key: "shops", label: "Shop", built: true },
  { key: "usage", label: "Usage", built: true },
];

export function ShopNav({ tenantId, current }: { tenantId: string; current: ShopScreen }) {
  return (
    <nav className="flex flex-wrap gap-1 border-b pb-px" aria-label="Screens">
      {SCREENS.map((screen) =>
        screen.built ? (
          <Link
            key={screen.key}
            href={`/console/${encodeURIComponent(tenantId)}/${screen.key}`}
            aria-current={screen.key === current ? "page" : undefined}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
              screen.key === current
                ? "border-foreground font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {screen.label}
          </Link>
        ) : (
          <span
            key={screen.key}
            title="Designed, not built yet."
            className="-mb-px cursor-not-allowed border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground/50"
          >
            {screen.label}
          </span>
        ),
      )}
    </nav>
  );
}
