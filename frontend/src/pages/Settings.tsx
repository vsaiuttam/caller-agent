/**
 * Settings: the workspace itself. Integrations (apps, telephony, messaging,
 * webhooks) moved to their own page; old links are forwarded:
 *
 *   ?tab=workspace (default)  what's connected, at a glance, and where to fix it
 *   ?tab=team                 people and invites (owner and admin, with accounts)
 *   ?tab=security             sign-in, sessions, secrets at rest
 *
 *   ?connect=1, ?tab=apps, ?tab=services   → /app/integrations (v2 links)
 */

import { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { canManageTeam, useAuth } from "../auth";
import { IconArrowRight, IconChip, IconLock, IconPhone, IconPlug, IconRefresh, IconSettings, IconShield, IconUsers } from "../components/icons";
import { ServiceGroup } from "../components/integrations/Services";
import { Team } from "../components/team/Team";
import { Badge, Button, Callout, Card, CardHeader, Page, PageHeader, Skeleton, Stat, Tabs, cx } from "../components/ui";
import { useHealth } from "../data";
import { useDocumentTitle } from "../hooks";

type Tab = "workspace" | "team" | "security";

const DESCRIPTION: Record<Tab, string> = {
  workspace: "This workspace at a glance: what's connected, and where each part is set up.",
  team: "Who can sign in, and invites for new people.",
  security: "Who can open this console, how long sessions last, and how secrets are stored.",
};

export default function Settings() {
  const auth = useAuth();
  const [params, setParams] = useSearchParams();
  const teamAvailable = auth.registration !== null && canManageTeam(auth.user);
  const requested = params.get("tab");
  const tab: Tab = requested === "security" ? "security" : requested === "team" && teamAvailable ? "team" : "workspace";
  useDocumentTitle(tab === "team" ? "Team" : "Settings");

  // v2 links: connected apps and services live under Integrations now.
  if (params.has("connect") || requested === "apps") return <Navigate to={`/app/integrations${params.has("connect") ? "?connect=1" : ""}`} replace />;
  if (requested === "services") return <Navigate to="/app/integrations?tab=telephony" replace />;

  const setTab = (value: Tab) => {
    const next = new URLSearchParams(params);
    if (value === "workspace") next.delete("tab");
    else next.set("tab", value);
    setParams(next, { replace: true });
  };

  return (
    <Page>
      <PageHeader icon={<IconSettings size={18} />} title="Settings" description={DESCRIPTION[tab]} />
      <Tabs
        label="Settings"
        value={tab}
        onChange={setTab}
        className="mb-5"
        tabs={[
          { value: "workspace", label: "Workspace", icon: <IconSettings size={15} /> },
          ...(teamAvailable ? [{ value: "team" as const, label: "Team", icon: <IconUsers size={15} /> }] : []),
          { value: "security", label: "Security", icon: <IconShield size={15} /> },
        ]}
      />
      <div role="tabpanel" aria-label={tab}>
        {tab === "workspace" ? <Workspace /> : tab === "team" ? <Team /> : <Security />}
      </div>
    </Page>
  );
}

function Workspace() {
  const { health, reload } = useHealth();
  const [refreshing, setRefreshing] = useState(false);
  const recheck = () => {
    setRefreshing(true);
    reload();
    window.setTimeout(() => setRefreshing(false), 800);
  };

  const places = [
    {
      to: "/app/ai-models",
      icon: <IconChip size={17} />,
      title: "AI models",
      hint: "Providers, defaults and costs",
      ok: health ? health.can_run_simulations : null,
      status: health?.provider_label || "No provider",
    },
    {
      to: "/app/integrations?tab=telephony",
      icon: <IconPhone size={17} />,
      title: "Telephony",
      hint: "Real calls through Twilio or Telnyx",
      ok: health ? health.can_place_calls : null,
      status: health ? (health.can_place_calls ? cap(health.telephony_mode) : "Mocked") : "",
    },
    {
      to: "/app/integrations",
      icon: <IconPlug size={17} />,
      title: "Connected apps",
      hint: "Tools over MCP",
      ok: health?.mcp_servers === undefined ? null : health.mcp_servers > 0,
      status: health?.mcp_servers === undefined ? "" : `${health.mcp_servers} connected`,
    },
  ];

  return (
    <div className="space-y-5">
      {!health ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Stat label="Connected" value={health.live.length} hint="Services with credentials" />
          <Stat label="Not set up" value={health.mocked.length} hint="Running on mocks or off" accent={health.mocked.length > 0} />
          <Stat label="Telephony" value={<span className="font-sans capitalize">{health.telephony_mode}</span>} hint={health.can_place_calls ? "Real calls on" : "Rehearsals only"} />
        </div>
      )}

      {health?.note && <Callout tone="info">{health.note}</Callout>}

      <Card className="overflow-hidden">
        <CardHeader
          title="Where things are set up"
          action={
            <Button size="sm" variant="ghost" icon={<IconRefresh size={13} />} loading={refreshing} onClick={recheck}>
              Re-check
            </Button>
          }
        />
        <ul className="divide-y divide-line">
          {places.map((p) => (
            <li key={p.to}>
              <Link to={p.to} className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-subtle/60">
                <span className={cx("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", p.ok ? "bg-good/12 text-good" : "bg-subtle text-ink-muted")}>{p.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-ink">{p.title}</span>
                  <span className="block text-xs text-ink-muted">{p.hint}</span>
                </span>
                {p.ok !== null && <Badge tone={p.ok ? "good" : "warning"}>{p.status}</Badge>}
                <IconArrowRight size={14} className="shrink-0 text-ink-muted" />
              </Link>
            </li>
          ))}
        </ul>
      </Card>

      <ServiceGroup title="Core" subtitle="Without these, nothing can talk or be saved." keys={["database", "model_provider"]} />
    </div>
  );
}

function Security() {
  const { health } = useHealth();
  const auth = useAuth();
  const authOn = health?.auth_enabled ?? auth.enabled;

  if (!health) return <Skeleton className="h-48 rounded-xl" />;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Access" subtitle="Who can open this console and place calls." icon={<IconLock size={16} />} />
        <div className="flex items-start gap-3 px-5 py-4">
          <span className={cx("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", authOn ? "bg-good/12 text-good" : "bg-warning/12 text-warning")}>
            <IconShield size={16} />
          </span>
          <div className="min-w-0 flex-1 text-sm">
            <p className="font-medium text-ink">{authOn ? "Sign-in required" : "Open to anyone with the link"}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">
              {authOn
                ? "Every API call and live stream needs a session. Sessions expire after AUTH_TOKEN_TTL_HOURS (12 by default)."
                : health.accounts
                  ? "Create the owner account (or set ADMIN_PASSWORD on the server) to require a sign-in."
                  : "Set ADMIN_PASSWORD on the server and restart to require a password. Optionally set AUTH_SECRET to keep sessions valid across password changes."}
            </p>
            {health.accounts && (
              <p className="mt-1.5 text-xs text-ink-muted">
                {health.accounts.users === 1 ? "1 account" : `${health.accounts.users} accounts`}. New people join by{" "}
                {health.accounts.registration_mode === "open" ? "registering (open)" : health.accounts.registration_mode === "closed" ? "nothing: registration is closed" : "invite"}. Set
                REGISTRATION_MODE to change it.
              </p>
            )}
            {!authOn && health.accounts && (
              <Link to="/register" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
                Create the owner account <IconArrowRight size={12} />
              </Link>
            )}
          </div>
          <Badge tone={authOn ? "good" : "warning"}>{authOn ? "On" : "Off"}</Badge>
        </div>
      </Card>

      <Card>
        <CardHeader title="Secrets at rest" subtitle="Provider keys, app URLs and headers stored by the console." icon={<IconLock size={16} />} />
        <div className="flex items-start gap-3 px-5 py-4 text-sm">
          <div className="min-w-0 flex-1">
            <p className="font-medium text-ink">{health.secrets_sealed === false ? "Stored unencrypted" : "Encrypted"}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">
              {health.secrets_sealed === false
                ? "Set SECRETS_KEY (or AUTH_SECRET) on the server and restart to encrypt them. Keys are never shown again either way."
                : "Keys are sealed before they're saved and never returned by the API, only their last four characters."}
            </p>
          </div>
          <Badge tone={health.secrets_sealed === false ? "warning" : "good"}>{health.secrets_sealed === false ? "Off" : "On"}</Badge>
        </div>
      </Card>
    </div>
  );
}

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
