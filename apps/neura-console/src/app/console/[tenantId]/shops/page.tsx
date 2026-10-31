/**
 * Screen 4 — Shop connection. Redesigned 2026-09-28 from the owner's approved
 * mockup (console.md §3.4, canvas boards 21 and 23).
 *
 * The owner found it thin and asked what connecting a new shop takes. It is now
 * four parts, in the order an owner needs them:
 *
 * - **Get set up** — a checklist, each step ticked or not yet, and who does it:
 *   connected, passes the check (*Check now*, still a click), catalogue copied, chat box
 *   on the shop; then, optional and needed for Sold out, the data agreement and
 *   product views arriving. Every tick but *answers* is read from our own
 *   tables.
 * - **Your shop's contact details** (2026-10-02, ADR-0055, G44): an email and a
 *   phone, both optional, named to a shopper the assistant hands over; under the
 *   form, the server's own sentence a shopper reads.
 * - **Our copy of your catalogue** — counts, when it was last read, *"nothing
 *   syncs by itself yet"*, **Sync now** (writes our copy, never the shop), each
 *   kind's last run, and how much search by meaning covers.
 * - **What your shop lets the assistant do** — the shop's own declaration in
 *   plain words, from the last check; and always *Read only*.
 * - **Connection details** — for a developer or support.
 *
 * **Since 2026-10-01 the owner connects their own shop here** (ADR-0052, canvas
 * row 10): *Connect your shop* replaces *"No shop connected yet"*. NEURA makes
 * the shop token and shows it **once**; the browser never sends one, only the
 * bridge's address. *Check now* became the **full check**, run in the
 * background; a connected shop gains *Your shop token* with *Make a new token*.
 * **No stored credential is displayed, not even masked**: a token appears only
 * in the response that made it.
 *
 * **Nothing here reaches the shop on a page load.** The check is a button; the
 * page first shows the **last** check, read from our own table (`ShopChecks`),
 * so it can be re-read after a sync without asking the shop again.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { AllowedList, CheckItem, ShopChecks } from "@/components/shop/full-check";
import { ConnectShop } from "@/components/shop/connect-shop";
import { CustomerSecret } from "@/components/shop/customer-secret";
import { ShopContact } from "@/components/shop/shop-contact";
import { ShopToken } from "@/components/shop/shop-token";
import { SetupItem } from "@/components/shop/setup-item";
import { hasCare, hasSell, shopAssistants } from "@/lib/shop-assistants";
import { SyncNow } from "@/components/shop/sync-now";
import { When } from "@/components/when";
import type { CustomerSecretView, ShopContactView } from "@/lib/api";
import { fromApi, hasSession } from "@/lib/server-api";
import { PERMISSION, refusal } from "@/lib/roles";
import { NotAllowed } from "@/components/not-allowed";
import {
  ENTITY_LABELS,
  SHOWN_KINDS,
  connectionKind,
  counted,
  host,
  readLine,
  type ConnectedStore,
  type ShopView,
} from "@/lib/shop";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default async function ShopPage({ params }: { params: Promise<{ tenantId: string }> }) {
  if (!(await hasSession())) redirect("/");

  const { tenantId } = await params;
  // A role that does not include this screen sees why, not an error (ADR-0058).
  const refused = await refusal(tenantId, PERMISSION.connection);
  if (refused) return <NotAllowed refusal={refused} what="Shop connection" />;
  const [view, assistants, contact, secret] = await Promise.all([
    fromApi<ShopView>(`/shops/${encodeURIComponent(tenantId)}/store`),
    shopAssistants(tenantId),
    fromApi<ShopContactView>(`/shops/${encodeURIComponent(tenantId)}/contact`),
    fromApi<CustomerSecretView>(`/shops/${encodeURIComponent(tenantId)}/customer-secret`),
  ]);
  const sell = hasSell(assistants);
  // ADR-0057 §3: for a shop that can answer order questions, NEURA-CARE with a
  // bridge that looks orders up. A shop whose last check is unknown shows it,
  // as `hasSell` does: hiding a part because a read failed loses it silently.
  const answersOrders =
    view.ok &&
    view.data.connected &&
    hasCare(assistants) &&
    view.data.stores.some(
      (store) =>
        !store.last_check?.result || store.last_check.result.capabilities.includes("order.read"),
    );

  return (
    <>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Shop connection</h1>
        <p className="text-muted-foreground">
          How your assistant is connected to your shop, and whether everything is set up.
        </p>
      </div>

      {!view.ok ? (
        <Alert variant="destructive">
          <AlertTitle>
            {view.status === 404 ? "No such shop, or no access to it" : "Could not load"}
          </AlertTitle>
          <AlertDescription>
            {view.status === 404
              ? "Your account does not hold a live membership for this shop."
              : view.message}
          </AlertDescription>
        </Alert>
      ) : (
        <ShopChecks tenantId={tenantId} stores={view.data.stores}>
          {view.data.connected ? null : (
            <ConnectShop
              tenantId={tenantId}
              initial={view.data.connect ?? { token_made_at: null, last_check: null }}
            />
          )}
          <GetSetUp tenantId={tenantId} view={view.data} sell={sell} />
          <ShopContact tenantId={tenantId} initial={contact.ok ? contact.data : null} />
          {answersOrders && secret.ok ? (
            <CustomerSecret
              tenantId={tenantId}
              madeAt={secret.data.made_at}
              madeBy={secret.data.made_by}
            />
          ) : null}
          {view.data.connected ? (
            <>
              {view.data.stores.map((store) => (
                <ShopToken
                  key={`token-${store.id}`}
                  tenantId={tenantId}
                  storeId={store.id}
                  setAt={store.token_set_at}
                  setBy={store.token_made_by}
                  named={view.data.stores.length > 1 ? host(store.base_url) : null}
                />
              ))}
              {view.data.stores.map((store) => (
                <StoreParts
                  key={store.id}
                  tenantId={tenantId}
                  store={store}
                  named={view.data.stores.length > 1}
                />
              ))}
              <ConnectionDetails tenantId={tenantId} stores={view.data.stores} />
            </>
          ) : null}
        </ShopChecks>
      )}
    </>
  );
}

/** When products were last read from the shop — `null` if never. */
function lastRead(store: ConnectedStore): string | null {
  return store.syncs.find((sync) => sync.entity_type === "product")?.completed_at ?? null;
}

/** `sell`: the two optional steps are for Sold out, a NEURA-SELL screen — not listed without it. */
function GetSetUp({ tenantId, view, sell }: { tenantId: string; view: ShopView; sell: boolean }) {
  const setup = view.setup;
  const several = view.stores.length > 1;

  return (
    <section aria-labelledby="get-set-up" className="overflow-hidden rounded-2xl border">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b px-4 py-3.5 sm:px-5">
        <h2 id="get-set-up" className="text-lg font-semibold">
          Get set up
        </h2>
        {view.connected ? (
          <Link
            href={`/console/${encodeURIComponent(tenantId)}/help`}
            className="inline-flex items-center gap-1 text-sm font-medium underline-offset-3 hover:underline"
          >
            Help: connecting your shop <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        ) : null}
      </div>

      <ul className="divide-y">
        {view.connected ? (
          view.stores.map((store) => <StoreSteps key={store.id} store={store} named={several} />)
        ) : (
          <SetupItem
            item="connected"
            state="not-yet"
            title="Your shop is connected"
            detail="Not yet · connect it above, in three steps"
          />
        )}

        {setup ? <ChatBoxStep chatBox={setup.chat_box} /> : null}
      </ul>

      {setup && sell ? (
        <>
          <p className="border-t px-4 pt-3 pb-1 text-xs font-medium text-muted-foreground sm:px-5">
            Optional: needed for Product views
          </p>
          <ul className="divide-y">
            <SetupItem
              compact
              item="agreement"
              state={setup.agreement_since ? "done" : "not-yet"}
              title="Data agreement on record"
              detail={
                setup.agreement_since ? (
                  <>
                    Since <When iso={setup.agreement_since} date />
                  </>
                ) : (
                  "Not recorded yet · FiveNeurals records it"
                )
              }
            />
            <SetupItem
              compact
              item="views"
              state={setup.receiving ? "done" : "not-yet"}
              title="Your shop is sending product views"
              detail={
                setup.receiving
                  ? `Some arrived in the last ${setup.window_days} days`
                  : !setup.agreement_since
                    ? "Needs the data agreement first"
                    : `None arrived in the last ${setup.window_days} days · your developer switches them on in your shop's settings`
              }
            />
          </ul>
        </>
      ) : null}
    </section>
  );
}

/** The three steps that belong to one connection. Named only when there is more than one. */
function StoreSteps({ store, named }: { store: ConnectedStore; named: boolean }) {
  const read = lastRead(store);
  const products = store.catalogue.product ?? 0;
  return (
    <>
      {named ? (
        <li className="bg-muted/30 px-4 py-2 text-xs font-medium text-muted-foreground sm:px-5">
          {host(store.base_url)}
        </li>
      ) : null}
      <SetupItem
        item="connected"
        store={store.id}
        state={store.status === "active" ? "done" : "failed"}
        title="Your shop is connected"
        detail={
          store.status === "active"
            ? host(store.base_url)
            : `${host(store.base_url)} · the connection is ${store.status}`
        }
      />
      <CheckItem storeId={store.id} />
      <SetupItem
        item="catalogue"
        state={read ? "done" : "not-yet"}
        title="Your catalogue is copied"
        detail={
          read ? (
            <>
              {counted(products, "product")} · last read <When iso={read} inline />
            </>
          ) : (
            "Not yet · press Sync now below"
          )
        }
      />
    </>
  );
}

function ChatBoxStep({ chatBox }: { chatBox: NonNullable<ShopView["setup"]>["chat_box"] }) {
  const where = chatBox ? chatBox.origins.map(host) : [];
  const from =
    where.length === 1
      ? ` from ${where[0]}`
      : where.length > 1
        ? ` · works on ${where.join(", ")}`
        : "";

  return (
    <SetupItem
      item="chat-box"
      state={chatBox?.last_used_at ? "done" : "not-yet"}
      title="The chat box is on your shop"
      detail={
        chatBox?.last_used_at ? (
          <>
            Used <When iso={chatBox.last_used_at} day />
            {from} · added by your developer
          </>
        ) : chatBox ? (
          "Not used yet — this is ticked once a shopper uses it · added by your developer"
        ) : (
          "Not yet · your developer adds it, with a key from FiveNeurals"
        )
      }
    />
  );
}

/** The two cards that belong to one connection: our copy, and what the shop allows. */
function StoreParts({
  tenantId,
  store,
  named,
}: {
  tenantId: string;
  store: ConnectedStore;
  named: boolean;
}) {
  const read = lastRead(store);
  const note = (key: string) => store.notes.find((n) => n.key === key)?.text;
  const byKind = new Map(store.syncs.map((sync) => [sync.entity_type, sync]));

  return (
    <div className="grid items-start gap-5 lg:grid-cols-2">
      <section
        aria-label={named ? `Our copy of ${host(store.base_url)}` : "Our copy of your catalogue"}
        data-store={store.id}
        className="space-y-4 rounded-2xl border p-4 sm:p-5"
      >
        <h2 className="text-lg font-semibold">
          Our copy of your catalogue
          {named ? (
            <span className="font-normal text-muted-foreground"> · {host(store.base_url)}</span>
          ) : null}
        </h2>

        <ul className="grid grid-cols-3 gap-2.5">
          {SHOWN_KINDS.map((kind) => (
            <li key={kind} data-count={kind} className="rounded-xl border px-3 py-2.5 sm:px-3.5">
              <span className="block text-2xl font-semibold tabular-nums">
                {store.catalogue[kind] ?? 0}
              </span>
              <span className="block text-sm text-muted-foreground">
                {(ENTITY_LABELS[kind] ?? kind).toLowerCase()}
              </span>
            </li>
          ))}
        </ul>

        <p className="leading-relaxed">
          {read ? (
            <>
              Last read from your shop{" "}
              <strong className="font-semibold">
                <When iso={read} inline />
              </strong>
              .{" "}
            </>
          ) : (
            "Nothing has been read from your shop yet. "
          )}
          <span className="text-muted-foreground">{note("no_schedule")}</span>
        </p>

        <SyncNow tenantId={tenantId} storeId={store.id} asked={store.sync_asked} lastRead={read} />

        <div className="space-y-1.5 border-t pt-3 text-sm text-muted-foreground">
          {SHOWN_KINDS.filter((kind) => byKind.has(kind)).map((kind) => {
            const sync = byKind.get(kind)!;
            return (
              <p key={kind} data-kind={kind}>
                {ENTITY_LABELS[kind]} — {readLine(sync, store.catalogue[kind] ?? 0)}
                {sync.in_progress ? " · part-way through" : ""}
              </p>
            );
          })}
          {note("index") ? (
            <p data-index className="pt-1.5 text-foreground/80">
              {note("index")}
            </p>
          ) : null}
        </div>
      </section>

      <section
        aria-label={named ? `What ${host(store.base_url)} allows` : "What your shop allows"}
        className="space-y-3.5 rounded-2xl border p-4 sm:p-5"
      >
        <h2 className="text-lg font-semibold">What your shop lets the assistant do</h2>
        <AllowedList storeId={store.id} />
        <p className="rounded-xl bg-muted/60 px-3.5 py-3 text-sm leading-relaxed">
          <strong className="font-semibold">Read only.</strong> Your assistant cannot change
          anything in your shop — no orders, prices or stock.
        </p>
      </section>
    </div>
  );
}

function ConnectionDetails({ tenantId, stores }: { tenantId: string; stores: ConnectedStore[] }) {
  return (
    <section aria-labelledby="details" className="space-y-3 rounded-2xl border p-4 sm:p-5">
      <h2 id="details" className="font-semibold">
        Connection details{" "}
        <span className="font-normal text-muted-foreground">· for your developer or support</span>
      </h2>
      {stores.map((store) => (
        <dl
          key={store.id}
          className="grid gap-x-6 gap-y-2.5 text-sm sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr]"
        >
          <Detail label="Address">
            <code className="break-all">{store.base_url}</code>
          </Detail>
          <Detail label="Connection">{connectionKind(store.platform)}</Detail>
          <Detail label="Status">
            {store.status.charAt(0).toUpperCase() + store.status.slice(1)}
          </Detail>
        </dl>
      ))}
      {/* The one place the id is shown: it means nothing to an owner until
          support asks which shop they mean. */}
      <dl className="text-sm">
        <Detail label="Shop ID, if support asks">
          <code className="break-all">{tenantId}</code>
        </Detail>
      </dl>
    </section>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
