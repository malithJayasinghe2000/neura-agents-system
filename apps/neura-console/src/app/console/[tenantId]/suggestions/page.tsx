/**
 * Screen 7 — Suggestions. ADR-0050: the shop owner may choose what is
 * suggested with each product, and their choice wins.
 *
 * Every product, what a shopper's basket shows with it now, and who decided:
 * the owner, the AI, or "automatic, decided when first shown". Served by SELL's
 * own routes (`/v1/sell/console/...`), so a shop without SELL gets a plain
 * sentence rather than an empty list pretending to be one.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { SuggestionEditor } from "@/components/suggestions/suggestion-editor";
import { fromApi, hasSession } from "@/lib/server-api";
import type { SuggestionsPage } from "@/lib/suggestions";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default async function SuggestionsScreen({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ q?: string; after?: string }>;
}) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  const { q = "", after = "" } = await searchParams;
  const query = new URLSearchParams();
  if (q) query.set("q", q);
  if (after) query.set("after", after);

  const result = await fromApi<SuggestionsPage>(
    `/shops/${encodeURIComponent(tenantId)}/suggestions${query.size ? `?${query}` : ""}`,
    "/v1/sell/console",
  );

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Suggestions</h1>
        <p className="text-muted-foreground">
          What a shopper&apos;s basket suggests with each product — and your way to change it.
        </p>
      </div>

      {!result.ok ? (
        <Alert variant={result.status === 403 ? "default" : "destructive"}>
          <AlertTitle>
            {result.status === 404
              ? "No such shop, or no access to it"
              : result.status === 403
                ? "Suggestions are not part of this shop's plan"
                : "Could not load"}
          </AlertTitle>
          <AlertDescription>{result.message}</AlertDescription>
        </Alert>
      ) : (
        <>
          <form className="flex max-w-md gap-2" action="">
            <Input
              name="q"
              defaultValue={q}
              placeholder="Find a product"
              aria-label="Find a product"
            />
            <Button type="submit" size="sm" variant="secondary">
              Find
            </Button>
          </form>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Your products</CardTitle>
              <CardDescription>
                Same for every shopper. A shopper sees at most two, and only ones in stock at that
                moment. Your choice always wins — nothing automatic replaces it.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {result.data.products.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {q
                    ? "No product matches that."
                    : "No products yet. They appear here once your shop's catalogue has synced."}
                </p>
              ) : (
                <ul className="divide-y">
                  {result.data.products.map((product) => (
                    <SuggestionEditor
                      key={product.product_id}
                      tenantId={tenantId}
                      product={product}
                      maxChosen={result.data.max_chosen}
                    />
                  ))}
                </ul>
              )}
              {result.meta.has_more && result.meta.next_cursor ? (
                <div className="pt-3">
                  <Button
                    size="sm"
                    variant="outline"
                    nativeButton={false}
                    render={
                      <Link
                        href={`/console/${encodeURIComponent(tenantId)}/suggestions?${new URLSearchParams(
                          { ...(q ? { q } : {}), after: result.meta.next_cursor },
                        )}`}
                      />
                    }
                  >
                    More products
                  </Button>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      )}
    </>
  );
}
