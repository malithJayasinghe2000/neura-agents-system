/**
 * Screen 4 — Shop connection. Redesigned 2026-09-28 from the owner's approved
 * mockup (console.md §3.4, canvas boards 21 and 23).
 *
 * The owner found it thin and asked what connecting a new shop takes. It is now
 * four parts, in the order an owner needs them:
 *
 * - **Get set up** — a checklist, each step ticked or not yet, and who does it:
 *   connected, answers (*Check now*, still a click), catalogue copied, chat box
 *   on the shop; then, optional and needed for Sold out, the data agreement and
 *   product views arriving. Every tick but *answers* is read from our own
 *   tables.
 * - **Our copy of your catalogue** — counts, when it was last read, *"nothing
 *   syncs by itself yet"*, **Sync now** (writes our copy, never the shop), each
 *   kind's last run, and how much search by meaning covers.
 * - **What your shop lets the assistant do** — the shop's own declaration in
 *   plain words, after *Check now*; and always *Read only*.
 * - **Connection details** — for a developer or support.
 *
 * **Still read-only towards the shop.** The connect form stays unbuilt (§3.4:
 * a credential form would be the highest-value target in the application), and
 * **no credential is displayed, not even masked** — guaranteed by the query,
 * which never selects those columns, not by this file.
 *
 * **Nothing here reaches the shop on a page load.** *Check now* is a button;
 * its answer lives in the page (`HealthChecks`), not in the address, so the
 * page can be re-read after a sync without asking the shop again.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { AllowedList, AnswersItem, HealthChecks } from "@/components/shop/health-check";
import { SetupItem } from "@/components/shop/setup-item";
import { SyncNow } from "@/components/shop/sync-now";
import { When } from "@/components/when";
import { fromApi, hasSession } from "@/lib/server-api";
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
  const view = await fromApi<ShopView>(`/shops/${encodeURIComponent(tenantId)}/store`);

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
        <HealthChecks tenantId={tenantId}>
          <GetSetUp tenantId={tenantId} view={view.data} />
          {view.data.connected ? (
            <>
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
          ) : (
            <NotConnected />
          )}
        </HealthChecks>
      )}
    </>
  );
}

/** When products were last read from the shop — `null` if never. */
function lastRead(store: ConnectedStore): string | null {
  return store.syncs.find((sync) => sync.entity_type === "product")?.completed_at ?? null;
}

function GetSetUp({ tenantId, view }: { tenantId: string; view: ShopView }) {
  const setup = view.setup;
  const several = view.stores.length > 1;

  return (
    <section aria-labelledby="get-set-up" className="overflow-hidden rounded-2xl border">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b px-4 py-3.5 sm:px-5">
        <h2 id="get-set-up" className="text-lg font-semibold">
          Get set up
        </h2>
        <Link
          href={`/console/${encodeURIComponent(tenantId)}/help`}
          className="inline-flex items-center gap-1 text-sm font-medium underline-offset-3 hover:underline"
        >
          Help: connecting your shop <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </div>

      <ul className="divide-y">
        {view.connected ? (
          view.stores.map((store) => <StoreSteps key={store.id} store={store} named={several} />)
        ) : (
          <SetupItem
            item="connected"
            state="not-yet"
            title="Your shop is connected"
            detail="Not yet · FiveNeurals connects it, with your shop's address and its secret token"
          />
        )}

        {setup ? <ChatBoxStep chatBox={setup.chat_box} /> : null}
      </ul>

      {setup ? (
        <>
          <p className="border-t px-4 pt-3 pb-1 text-xs font-medium text-muted-foreground sm:px-5">
            Optional — needed for Sold out
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
            ? `${host(store.base_url)} · set up by FiveNeurals`
            : `${host(store.base_url)} · the connection is ${store.status}`
        }
      />
      <AnswersItem storeId={store.id} />
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

/**
 * The empty state that matters most on this screen: nothing is connected, so
 * nothing anywhere else in the console will ever have data in it.
 */
function NotConnected() {
  return (
    <section className="space-y-2 rounded-2xl border border-dashed p-5 sm:p-7">
      <h2 className="text-lg font-semibold">No shop connected yet</h2>
      <p className="leading-relaxed">
        Until a shop is connected, your assistant has no catalogue to answer from and no orders to
        look up — every other screen here stays empty.
      </p>
      <p className="leading-relaxed text-muted-foreground">
        Connecting is not done from this screen: it needs your shop&apos;s address and its secret
        token, and those go in through FiveNeurals rather than through a form in a browser. This
        page fills in as soon as they have.
      </p>
    </section>
  );
}
