/**
 * Settings → Team (owner and admin only; accounts spec §3).
 *
 *   People   everyone with an account: role, disable, remove. The server's
 *            guards are mirrored here so a control that would be refused is
 *            never offered: the owner can't be changed, admins can't change
 *            other admins, nobody disables or removes themselves, and only
 *            the owner makes admins.
 *   Invites  create one (email optional, role, expiry) and see its code once,
 *            as a copyable `<origin>/register?invite=<code>` link; pending
 *            invites can be revoked.
 *
 * A backend from before accounts answers 404 here; the page says so instead
 * of failing.
 */

import { useState, type FormEvent } from "react";
import { ApiError, api, type CreatedInvite, type TeamInvite, type TeamUser, type UserRole } from "../../api";
import { ROLE_LABEL, useAuth } from "../../auth";
import { formatDateTime, formatRelative } from "../../format";
import { useAsync } from "../../hooks";
import { IconCheck, IconCopy, IconPlus, IconTrash, IconUsers } from "../icons";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  Dialog,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Select,
  Skeleton,
  Switch,
  cx,
  toast,
  type Tone,
} from "../ui";

const ROLE_TONE: Record<UserRole, Tone> = { owner: "brand", admin: "info", member: "neutral" };

export function Team() {
  const { user: me } = useAuth();
  const users = useAsync(() => api.teamUsers(), []);
  const invites = useAsync(() => api.teamInvites(), []);
  const [inviteOpen, setInviteOpen] = useState(false);

  // FastAPI's own 404 says "Not Found": the route doesn't exist on this backend.
  const unsupported = [users, invites].some((r) => r.error && /^not found$/i.test(r.error.trim()));
  if (unsupported) {
    return (
      <Card>
        <EmptyState
          avatar="thinking"
          title="Team accounts aren't available on this server"
          hint="This backend predates accounts. Everyone signs in with the shared admin password until it's updated."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHeader
          title="People"
          subtitle="Everyone who can sign in to this console. Signed-in people can use the whole console; only the owner and admins manage the team."
          icon={<IconUsers size={16} />}
        />
        {users.error ? (
          <div className="p-5">
            <ErrorNote message={users.error} onRetry={users.reload} />
          </div>
        ) : !users.data ? (
          <div className="space-y-2 p-5" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : (
          <PeopleTable users={users.data} meId={me?.id ?? null} meRole={me?.role ?? "member"} onChanged={users.reload} />
        )}
      </Card>

      <Card className="overflow-hidden">
        <CardHeader
          title="Invites"
          subtitle="A code for one person to create an account. Each code works once and is shown only when it's created."
          action={
            <Button size="sm" icon={<IconPlus size={13} />} onClick={() => setInviteOpen(true)}>
              Invite someone
            </Button>
          }
        />
        {invites.error ? (
          <div className="p-5">
            <ErrorNote message={invites.error} onRetry={invites.reload} />
          </div>
        ) : !invites.data ? (
          <div className="space-y-2 p-5" aria-busy="true">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-11" />
            ))}
          </div>
        ) : (
          <InviteList invites={invites.data} onChanged={invites.reload} onCreate={() => setInviteOpen(true)} />
        )}
      </Card>

      <InviteDialog
        open={inviteOpen}
        canInviteAdmins={me?.role === "owner"}
        onClose={() => setInviteOpen(false)}
        onCreated={invites.reload}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------

/** Why this row can't be edited by the signed-in person, or null if it can. */
function lockReason(target: TeamUser, meId: string | null, meRole: UserRole): string | null {
  if (target.role === "owner") return "The owner can't be changed or removed.";
  if (target.id === meId) return "You can't change your own account here.";
  if (meRole === "admin" && target.role === "admin") return "Only the owner can change an admin.";
  return null;
}

function PeopleTable({
  users,
  meId,
  meRole,
  onChanged,
}: {
  users: TeamUser[];
  meId: string | null;
  meRole: UserRole;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [removing, setRemoving] = useState<TeamUser | null>(null);
  const order: Record<UserRole, number> = { owner: 0, admin: 1, member: 2 };
  const sorted = [...users].sort((a, b) => order[a.role] - order[b.role] || a.name.localeCompare(b.name));

  const update = async (target: TeamUser, body: { role?: "admin" | "member"; disabled?: boolean }, done: string) => {
    setBusy(target.id);
    try {
      await api.updateTeamUser(target.id, body);
      toast.success(done);
      onChanged();
    } catch (err) {
      toast.error(`Couldn't update ${target.name}`, (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!removing) return;
    const target = removing;
    setBusy(target.id);
    try {
      await api.removeTeamUser(target.id);
      toast.success(`${target.name} removed`, "Their sessions stop working immediately.");
      setRemoving(null);
      onChanged();
    } catch (err) {
      toast.error(`Couldn't remove ${target.name}`, (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (users.length === 0) {
    return <EmptyState compact title="No accounts yet" hint="Invite someone to create the first one." />;
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="data-table min-w-[40rem]">
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Role</th>
              <th scope="col">Last sign-in</th>
              <th scope="col">Access</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((u) => {
              const locked = lockReason(u, meId, meRole);
              const isMe = u.id === meId;
              return (
                <tr key={u.id} className={cx(u.disabled && "opacity-70")}>
                  <td>
                    <p className="font-medium text-ink">
                      {u.name}
                      {isMe && <span className="ml-1.5 text-xs font-normal text-ink-muted">(you)</span>}
                    </p>
                    <p className="text-xs text-ink-muted">{u.email || "Admin password session"}</p>
                  </td>
                  <td>
                    {locked || meRole !== "owner" ? (
                      <Badge tone={ROLE_TONE[u.role]} title={locked ?? "Only the owner can change roles"}>
                        {ROLE_LABEL[u.role]}
                      </Badge>
                    ) : (
                      <Select
                        aria-label={`Role for ${u.name}`}
                        value={u.role}
                        disabled={busy === u.id}
                        onChange={(e) =>
                          update(u, { role: e.target.value as "admin" | "member" }, `${u.name} is now ${e.target.value === "admin" ? "an admin" : "a member"}`)
                        }
                        className="w-32"
                      >
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </Select>
                    )}
                  </td>
                  <td className="tnum whitespace-nowrap text-xs text-ink-secondary">
                    {u.last_login_at ? (
                      <time dateTime={u.last_login_at} title={formatDateTime(u.last_login_at)}>
                        {formatRelative(u.last_login_at)}
                      </time>
                    ) : (
                      <span className="text-ink-muted">Never</span>
                    )}
                  </td>
                  <td>
                    {locked ? (
                      <Badge tone={u.disabled ? "critical" : "good"}>{u.disabled ? "Disabled" : "Active"}</Badge>
                    ) : (
                      <Switch
                        checked={!u.disabled}
                        disabled={busy === u.id}
                        onChange={(active) =>
                          update(u, { disabled: !active }, active ? `${u.name} can sign in again` : `${u.name} is disabled and signed out`)
                        }
                        label={<span className="text-xs font-medium">{u.disabled ? "Disabled" : "Active"}</span>}
                        className="w-28"
                      />
                    )}
                  </td>
                  <td className="text-right">
                    {!locked && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<IconTrash size={13} />}
                        disabled={busy === u.id}
                        onClick={() => setRemoving(u)}
                        aria-label={`Remove ${u.name}`}
                      >
                        Remove
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        size="sm"
        title={removing ? `Remove ${removing.name}?` : "Remove"}
        description="They're signed out everywhere and can't sign in again. To bring them back, send a new invite."
        footer={
          <>
            <Button variant="secondary" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy === removing?.id} onClick={remove}>
              Remove
            </Button>
          </>
        }
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Invites
// ---------------------------------------------------------------------------

const INVITE_TONE: Record<TeamInvite["status"], Tone> = { pending: "warning", used: "good", expired: "neutral", revoked: "neutral" };
const INVITE_LABEL: Record<TeamInvite["status"], string> = { pending: "Pending", used: "Used", expired: "Expired", revoked: "Revoked" };

function InviteList({ invites, onChanged, onCreate }: { invites: TeamInvite[]; onChanged: () => void; onCreate: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);

  const revoke = async (invite: TeamInvite) => {
    setBusy(invite.id);
    try {
      await api.revokeInvite(invite.id);
      toast.success("Invite revoked", "Its code no longer works.");
      onChanged();
    } catch (err) {
      toast.error("Couldn't revoke the invite", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (invites.length === 0) {
    return (
      <EmptyState
        compact
        avatar="idle"
        title="No invites yet"
        hint="Create one and send the link to a teammate. It works once."
        action={
          <Button size="sm" variant="secondary" icon={<IconPlus size={13} />} onClick={onCreate}>
            Invite someone
          </Button>
        }
      />
    );
  }

  return (
    <ul className="divide-y divide-line">
      {invites.map((invite) => (
        <li key={invite.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink">{invite.email ?? "Anyone with the code"}</p>
            <p className="text-xs text-ink-muted">
              {ROLE_LABEL[invite.role]} invite, created {formatRelative(invite.created_at)}
              {invite.status === "pending" && `, expires ${formatDateTime(invite.expires_at)}`}
              {invite.status === "used" && invite.used_at && `, used ${formatRelative(invite.used_at)}`}
            </p>
          </div>
          <Badge tone={INVITE_TONE[invite.status]}>{INVITE_LABEL[invite.status]}</Badge>
          {invite.status === "pending" && (
            <Button size="sm" variant="ghost" loading={busy === invite.id} onClick={() => revoke(invite)}>
              Revoke
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

function InviteDialog({
  open,
  canInviteAdmins,
  onClose,
  onCreated,
}: {
  open: boolean;
  canInviteAdmins: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"member" | "admin">("member");
  const [days, setDays] = useState("7");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedInvite | null>(null);
  const [copied, setCopied] = useState(false);

  const close = () => {
    onClose();
    // Reset after the exit animation so the code doesn't flash away mid-fade.
    window.setTimeout(() => {
      setEmail("");
      setRole("member");
      setDays("7");
      setError(null);
      setCreated(null);
      setCopied(false);
    }, 250);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = email.trim();
    if (trimmed && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setError("That doesn't look like an email address. Leave it empty to let anyone with the code join.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const invite = await api.createInvite({ email: trimmed || undefined, role, expires_in_days: Number(days) });
      setCreated(invite);
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const link = created ? `${window.location.origin}/register?invite=${encodeURIComponent(created.code)}` : "";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      toast.success("Invite link copied");
    } catch {
      toast.error("Couldn't copy", "Select the link and copy it by hand.");
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={created ? "Invite created" : "Invite someone"}
      description={
        created
          ? "Send this link to the person you're inviting. The code is shown only now; if it's lost, revoke it and create another."
          : "They'll create their own account with the code. It works once."
      }
      footer={
        created ? (
          <Button onClick={close}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" form="invite-form" loading={busy}>
              Create invite
            </Button>
          </>
        )
      }
    >
      {created ? (
        <div className="space-y-4">
          <Field label="Invite link">
            <div className="flex gap-2">
              <Input readOnly value={link} onFocus={(e) => e.currentTarget.select()} className="font-mono text-xs" />
              <Button variant="secondary" icon={copied ? <IconCheck size={14} /> : <IconCopy size={14} />} onClick={copy}>
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </Field>
          <p className="text-xs leading-relaxed text-ink-secondary">
            Code <code className="rounded bg-subtle px-1.5 py-0.5 font-mono text-ink">{created.code}</code>
            {created.email ? ` works only for ${created.email}` : " works for anyone who has it"}, as{" "}
            {created.role === "admin" ? "an admin" : "a member"}, until {formatDateTime(created.expires_at)}.
          </p>
        </div>
      ) : (
        <form id="invite-form" onSubmit={submit} className="space-y-4" noValidate>
          {error && <Callout tone="critical">{error}</Callout>}
          <Field label="Email" optional hint="If set, only this address can use the code.">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" autoComplete="off" />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Role" hint={canInviteAdmins ? undefined : "Only the owner can invite admins."}>
              <Select value={role} onChange={(e) => setRole(e.target.value as "member" | "admin")}>
                <option value="member">Member</option>
                <option value="admin" disabled={!canInviteAdmins}>
                  Admin
                </option>
              </Select>
            </Field>
            <Field label="Expires after">
              <Select value={days} onChange={(e) => setDays(e.target.value)}>
                {[1, 3, 7, 14, 30].map((d) => (
                  <option key={d} value={d}>
                    {d === 1 ? "1 day" : `${d} days`}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </form>
      )}
    </Dialog>
  );
}
