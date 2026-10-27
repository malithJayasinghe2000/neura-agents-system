"use client";

/**
 * People and Invite a person, from the owner's approved design (console.md §3.8,
 * boards 38, 39 and 41). The words are the boards'.
 *
 * **Display only, like every screen.** The rules are the API's: a shop always
 * keeps one Owner, a member cannot be invited again, the link is emailed and
 * never shown. A refusal the API gives (for example *A shop always keeps at
 * least one Owner*) is shown in its own words. After each change the page is
 * read again from the server (`router.refresh()`), so the list is never a guess.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, TriangleAlert } from "lucide-react";
import {
  cancelInvite,
  changeRole,
  removePerson,
  sendInvite,
  sendInviteAgain,
  type Invite,
} from "@/lib/api";
import { roleName } from "@/lib/role-names";
import { When } from "@/components/when";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export type Member = {
  user_id: string;
  name: string;
  email: string;
  role: string;
  joined_at: string;
  you: boolean;
};

export type PeopleView = { members: Member[]; invites: Invite[]; owners: number };

const ROLES = ["owner", "support", "developer"] as const;

/** What each role can do: the cards (board 38). Since R10's B the Developer also
 * edits the contact details, said plainly as the design allowed. */
const ROLE_WORDS: Record<(typeof ROLES)[number], string> = {
  owner:
    "Everything, including inviting and removing people. A shop always keeps at least one Owner.",
  support:
    "Reads chats and grades replies in Review. Can't open settings, keys, Usage, Suggestions or Sold out.",
  developer:
    "Shop connection and Help: connects your shop, makes its secrets and edits its contact details. Never sees shoppers' chats.",
};

/** The invite's choices (board 39): Owner last, with its warning. */
const INVITE_CHOICES: { role: (typeof ROLES)[number]; words: string }[] = [
  { role: "support", words: ROLE_WORDS.support },
  { role: "developer", words: ROLE_WORDS.developer },
  {
    role: "owner",
    words: "Everything you can do, including removing you. Choose it only for a partner.",
  },
];

type Notice = { kind: "sent" | "warning" | "error"; text: React.ReactNode } | null;

export function PeopleScreen({
  tenantId,
  shopName,
  view,
}: {
  tenantId: string;
  shopName: string;
  view: PeopleView;
}) {
  const router = useRouter();
  const [refreshing, startTransition] = useTransition();
  const [inviting, setInviting] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => startTransition(() => router.refresh());

  function act(work: Promise<unknown>, done?: () => void) {
    setBusy(true);
    setNotice(null);
    work
      .then(() => {
        done?.();
        refresh();
      })
      .catch((reason: unknown) =>
        setNotice({
          kind: "error",
          text: reason instanceof Error ? reason.message : "That didn't work. Try again.",
        }),
      )
      .finally(() => setBusy(false));
  }

  function sent(email: string, role: string, emailed: boolean) {
    setNotice(
      emailed
        ? {
            kind: "sent",
            text: (
              <>
                Invite sent to <strong className="font-semibold">{email}</strong> as{" "}
                {roleName(role)}. The link works for 7 days.
              </>
            ),
          }
        : {
            kind: "warning",
            text: (
              <>
                The invite for <strong className="font-semibold">{email}</strong> is ready, but the
                email could not be sent. Try Send again in a moment.
              </>
            ),
          },
    );
  }

  const working = busy || refreshing;

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">People</h1>
          <p className="text-muted-foreground">
            Who can open {shopName}&apos;s dashboard, and what each person can do.
          </p>
        </div>
        {inviting ? null : (
          <Button
            type="button"
            data-open-invite
            className="h-11 w-full sm:h-10 sm:w-auto"
            onClick={() => {
              setNotice(null);
              setInviting(true);
            }}
          >
            Invite a person
          </Button>
        )}
      </div>

      {inviting ? (
        <InviteForm
          tenantId={tenantId}
          onCancel={() => setInviting(false)}
          onSent={(email, role, emailed) => {
            setInviting(false);
            sent(email, role, emailed);
            refresh();
          }}
        />
      ) : null}

      {notice ? <NoticeLine notice={notice} /> : null}

      <ul
        data-people
        aria-label="People"
        className="divide-y overflow-hidden rounded-xl border md:divide-y"
      >
        <li className="hidden gap-4 bg-muted/40 px-5 py-2.5 text-xs font-medium text-muted-foreground md:grid md:grid-cols-[minmax(0,1.6fr)_180px_minmax(0,1fr)_220px]">
          <span>Person</span>
          <span>Role</span>
          <span>Status</span>
          <span />
        </li>
        {view.members.map((member) => (
          <MemberRow
            key={member.user_id}
            member={member}
            onlyOwner={member.role === "owner" && view.owners <= 1}
            working={working}
            onRole={(role) => act(changeRole(tenantId, member.user_id, role))}
            onRemove={() => setRemoving(member)}
          />
        ))}
        {view.invites.map((invite) => (
          <InviteRow
            key={invite.id}
            invite={invite}
            working={working}
            onAgain={() => {
              setBusy(true);
              setNotice(null);
              sendInviteAgain(tenantId, invite.id)
                .then((again) => {
                  sent(invite.email, invite.role, again.emailed);
                  refresh();
                })
                .catch((reason: unknown) =>
                  setNotice({
                    kind: "error",
                    text: reason instanceof Error ? reason.message : "That didn't work. Try again.",
                  }),
                )
                .finally(() => setBusy(false));
            }}
            onCancel={() => act(cancelInvite(tenantId, invite.id))}
          />
        ))}
      </ul>

      {removing ? (
        <div
          role="alertdialog"
          aria-labelledby="remove-title"
          data-remove-confirm
          className="space-y-3 rounded-xl border border-foreground px-4 py-4 sm:px-5"
        >
          <p id="remove-title" className="font-semibold">
            Remove {shownName(removing)}?
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {shownName(removing)} can&apos;t open this shop&apos;s dashboard from the next click.
            Everything done before stays in the record. You can invite them again later.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              type="button"
              data-confirm-remove
              className="h-11 sm:h-10"
              disabled={working}
              onClick={() => act(removePerson(tenantId, removing.user_id), () => setRemoving(null))}
            >
              Remove
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-11 sm:h-10"
              onClick={() => setRemoving(null)}
            >
              Keep
            </Button>
          </div>
        </div>
      ) : null}

      <section aria-labelledby="roles" className="space-y-3">
        <h2 id="roles" className="text-lg font-semibold">
          What each role can do
        </h2>
        <div className="grid gap-3 md:grid-cols-3">
          {ROLES.map((role) => (
            <div key={role} className="space-y-1.5 rounded-xl border px-4 py-3.5">
              <p className="font-semibold">{roleName(role)}</p>
              <p className="text-sm leading-relaxed text-muted-foreground">{ROLE_WORDS[role]}</p>
            </div>
          ))}
        </div>
      </section>

      <p className="text-sm leading-relaxed text-muted-foreground">
        Every invite, role change and removal is kept in your shop&apos;s record, with who did it.
      </p>
    </>
  );
}

/** A person's name, or their email when they never gave one. */
function shownName(member: Member): string {
  return member.name || member.email;
}

function MemberRow({
  member,
  onlyOwner,
  working,
  onRole,
  onRemove,
}: {
  member: Member;
  onlyOwner: boolean;
  working: boolean;
  onRole: (role: string) => void;
  onRemove: () => void;
}) {
  const named = Boolean(member.name);
  return (
    <li
      data-member={member.user_id}
      className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1.6fr)_180px_minmax(0,1fr)_220px] md:items-center md:gap-4 md:px-5 md:py-3.5"
    >
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="font-medium [overflow-wrap:anywhere]">
          {shownName(member)}
          {member.you ? " (you)" : ""}
        </span>
        {named ? (
          <span className="text-sm text-muted-foreground [overflow-wrap:anywhere]">
            {member.email}
          </span>
        ) : null}
      </span>
      <span>
        {member.you ? (
          <span className="text-sm font-medium">{roleName(member.role)}</span>
        ) : (
          <select
            aria-label={`Role of ${shownName(member)}`}
            data-role-of={member.user_id}
            value={member.role}
            disabled={working}
            onChange={(event) => onRole(event.target.value)}
            className="h-11 w-full rounded-lg border bg-background px-2.5 text-sm md:h-9 md:w-auto"
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {roleName(role)}
              </option>
            ))}
          </select>
        )}
      </span>
      <span className="text-sm text-muted-foreground">
        {member.you && onlyOwner ? (
          "The only Owner, so this can't be removed"
        ) : (
          <>
            Joined <When iso={member.joined_at} date />
          </>
        )}
      </span>
      <span className="flex md:justify-end">
        {member.you ? null : (
          <Button
            type="button"
            variant="outline"
            data-remove={member.user_id}
            className="h-11 w-full md:h-9 md:w-auto"
            disabled={working}
            onClick={onRemove}
          >
            Remove
          </Button>
        )}
      </span>
    </li>
  );
}

function InviteRow({
  invite,
  working,
  onAgain,
  onCancel,
}: {
  invite: Invite;
  working: boolean;
  onAgain: () => void;
  onCancel: () => void;
}) {
  return (
    <li
      data-invite={invite.id}
      className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1.6fr)_180px_minmax(0,1fr)_220px] md:items-center md:gap-4 md:px-5 md:py-3.5"
    >
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="font-medium [overflow-wrap:anywhere]">{invite.email}</span>
        <span className="text-sm text-muted-foreground">
          Invite sent <When iso={invite.sent_at} date />
        </span>
      </span>
      <span className="text-sm font-medium">{roleName(invite.role)}</span>
      <span className="text-sm text-muted-foreground">
        {invite.expired ? (
          <>
            The link ended on <When iso={invite.expires_at} date />
          </>
        ) : (
          <>
            Waiting · the link works until <When iso={invite.expires_at} date />
          </>
        )}
      </span>
      <span className="flex flex-col gap-2 sm:flex-row md:justify-end">
        <Button
          type="button"
          variant="outline"
          data-send-again={invite.id}
          className="h-11 md:h-9"
          disabled={working}
          onClick={onAgain}
        >
          Send again
        </Button>
        <Button
          type="button"
          variant="outline"
          data-cancel-invite={invite.id}
          className="h-11 md:h-9"
          disabled={working}
          onClick={onCancel}
        >
          Cancel
        </Button>
      </span>
    </li>
  );
}

function InviteForm({
  tenantId,
  onCancel,
  onSent,
}: {
  tenantId: string;
  onCancel: () => void;
  onSent: (email: string, role: string, emailed: boolean) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!role) {
      setError("Choose their role.");
      return;
    }
    setSending(true);
    setError(null);
    sendInvite(tenantId, email.trim(), role)
      .then((result) => onSent(result.invite.email, result.invite.role, result.emailed))
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "The invite could not be sent."),
      )
      .finally(() => setSending(false));
  }

  return (
    <section
      aria-labelledby="invite-title"
      data-invite-form
      className="space-y-4 rounded-xl border border-foreground px-4 py-4 sm:px-5 sm:py-5"
    >
      <h2 id="invite-title" className="text-lg font-semibold">
        Invite a person
      </h2>
      <form onSubmit={submit} className="space-y-4">
        <div className="max-w-md space-y-1.5">
          <Label htmlFor="invite-email">Their email address</Label>
          <Input
            id="invite-email"
            name="email"
            type="email"
            required
            autoComplete="off"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="h-11 md:h-10"
          />
        </div>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Their role</legend>
          <div className="grid gap-3 md:grid-cols-3">
            {INVITE_CHOICES.map((choice) => (
              <label
                key={choice.role}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3.5",
                  role === choice.role ? "border-foreground" : null,
                )}
              >
                <input
                  type="radio"
                  name="role"
                  value={choice.role}
                  checked={role === choice.role}
                  onChange={() => setRole(choice.role)}
                  className="mt-1 size-4 accent-foreground"
                />
                <span className="space-y-1">
                  <span className="block font-semibold">{roleName(choice.role)}</span>
                  <span className="block text-sm leading-relaxed text-muted-foreground">
                    {choice.words}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <p className="text-sm leading-relaxed text-muted-foreground">
          We email them a link. It works once, for 7 days. They see only what their role allows, and
          you can change it or remove them at any time.
        </p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="submit" data-send-invite className="h-11 sm:h-10" disabled={sending}>
            Send invite
          </Button>
          <Button
            type="button"
            variant="outline"
            className="h-11 sm:h-10"
            disabled={sending}
            onClick={onCancel}
          >
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}

function NoticeLine({ notice }: { notice: NonNullable<Notice> }) {
  const Icon = notice.kind === "sent" ? CheckCircle2 : TriangleAlert;
  return (
    <div
      role={notice.kind === "error" ? "alert" : "status"}
      data-people-notice={notice.kind}
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3.5 text-sm leading-relaxed",
        notice.kind === "sent" ? "bg-muted/40" : null,
        notice.kind === "error" ? "border-destructive/50 text-destructive" : null,
      )}
    >
      <Icon className="mt-0.5 size-4.5 shrink-0" aria-hidden />
      <span>{notice.text}</span>
    </div>
  );
}
