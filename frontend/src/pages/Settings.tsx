/**
 * Integrations, in two tabs:
 *
 *   Connected apps  the user's own MCP servers — the tools the agent can use
 *                   (?connect=1 opens the connect dialog)
 *   Services        what this deployment is wired to, configured with
 *                   environment variables on the server (?tab=services)
 */

import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth";
import {
  IconBlock,
  IconCalendar,
  IconCampaign,
  IconCheck,
  IconChip,
  IconCoin,
  IconLock,
  IconMic,
  IconPhone,
  IconPlug,
  IconPlus,
  IconRefresh,
  IconSettings,
  IconShield,
  IconWhisper,
} from "../components/icons";
import type { ConnectIntent } from "../components/mcp/ConnectDialog";
import { ConnectedApps } from "../components/mcp/ConnectedApps";
import { Badge, Button, Callout, Card, CardHeader, ErrorNote, Page, PageHeader, Skeleton, Stat, Tabs, cx } from "../components/ui";
import { useHealth } from "../data";
import { useDocumentTitle } from "../hooks";

type Tab = "apps" | "services";

interface Integration {
  key: string;
  label: string;
  description: string;
  icon: ReactNode;
  configHint: string;
}

const GROUPS: Array<{ title: string; subtitle: string; items: Integration[] }> = [
  {
    title: "Core",
    subtitle: "Without these, nothing can talk or be saved.",
    items: [
      {
        key: "database",
        label: "Database",
        description: "Stores campaigns, contacts and every call.",
        icon: <IconCoin size={17} />,
        configHint: "Set DATABASE_URL.",
      },
      {
        key: "model_provider",
        label: "Model provider",
        description: "The LLM for the conversation and the post-call extraction.",
        icon: <IconChip size={17} />,
        configHint: "Set GEMINI_API_KEY, ANTHROPIC_API_KEY or OPENAI_API_KEY.",
      },
      {
        key: "telephony",
        label: "Telephony",
        description: "Places real phone calls through Twilio or Telnyx.",
        icon: <IconPhone size={17} />,
        configHint: "Set TELEPHONY=twilio with TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER (or the Telnyx equivalents).",
      },
    ],
  },
  {
    title: "Voice",
    subtitle: "How the agent hears and speaks.",
    items: [
      {
        key: "speech_to_text",
        label: "Speech-to-text",
        description: "Transcribes the person. Built into Twilio; Sarvam for Indian languages; Deepgram for LiveKit.",
        icon: <IconMic size={17} />,
        configHint: "Built in with Twilio. Otherwise set SARVAM_API_KEY or DEEPGRAM_API_KEY.",
      },
      {
        key: "text_to_speech",
        label: "Text-to-speech",
        description: "The agent's voice. Twilio Polly, Sarvam for Indian languages, or Cartesia.",
        icon: <IconWhisper size={17} />,
        configHint: "Built in with Twilio. Otherwise set SARVAM_API_KEY or CARTESIA_API_KEY.",
      },
    ],
  },
  {
    title: "After the call",
    subtitle: "Where outcomes go once the call ends.",
    items: [
      {
        key: "sms",
        label: "SMS follow-up",
        description: "Texts the person after each call, with delivery receipts.",
        icon: <IconCampaign size={17} />,
        configHint: "Uses the Twilio credentials. Turn it on per campaign.",
      },
      {
        key: "whatsapp",
        label: "WhatsApp follow-up",
        description: "WhatsApps the person after each call, with delivered/read receipts.",
        icon: <IconCampaign size={17} />,
        configHint: "Set TWILIO_WHATSAPP_FROM (Sandbox: +14155238886). Outside the Sandbox also set TWILIO_WHATSAPP_CONTENT_SID.",
      },
      {
        key: "calendar",
        label: "Calendar",
        description: "Books agreed appointments on a shared calendar.",
        icon: <IconCalendar size={17} />,
        configHint: "Set GOOGLE_CALENDAR_CREDENTIALS, or BUILTIN_CALENDAR=1 for the built-in one.",
      },
      {
        key: "records_api",
        label: "Records / CRM",
        description: "Writes collected fields to your CRM or ATS.",
        icon: <IconCoin size={17} />,
        configHint: "Set RECORDS_API_URL (and RECORDS_API_KEY), or BUILTIN_RECORDS=1.",
      },
      {
        key: "webhook_signing",
        label: "Webhook signing",
        description: "HMAC-SHA256 signatures so webhook receivers can verify us.",
        icon: <IconBlock size={17} />,
        configHint: "Set WEBHOOK_SIGNING_SECRET and share it with the receiver.",
      },
    ],
  },
];

export default function Settings() {
  useDocumentTitle("Integrations");
  const { reload } = useHealth();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "services" ? "services" : "apps";
  const [connect, setConnect] = useState<ConnectIntent | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // ?connect=1 (from the palette, the checklist, a campaign) opens the
  // dialog — also when this page is already open. It's one-shot: dropped
  // once honoured, so a reload doesn't reopen it.
  useEffect(() => {
    if (!params.has("connect")) return;
    setConnect("pick");
    const next = new URLSearchParams(params);
    next.delete("connect");
    setParams(next, { replace: true });
  }, [params, setParams]);

  const setTab = (value: Tab) => {
    const next = new URLSearchParams(params);
    if (value === "apps") next.delete("tab");
    else next.set("tab", value);
    setParams(next, { replace: true });
  };

  const refresh = () => {
    setRefreshing(true);
    reload();
    window.setTimeout(() => setRefreshing(false), 800);
  };

  return (
    <Page>
      <PageHeader
        icon={<IconSettings size={18} />}
        title="Integrations"
        description={
          tab === "apps"
            ? "Connect your own apps over MCP, so the agent can look things up during a call and record the outcome after it."
            : "What this deployment is connected to. Everything is configured with environment variables on the server, then a restart."
        }
        actions={
          tab === "apps" ? (
            <Button icon={<IconPlus size={14} />} onClick={() => setConnect("pick")}>
              Connect an app
            </Button>
          ) : (
            <Button variant="secondary" icon={<IconRefresh size={14} />} loading={refreshing} onClick={refresh}>
              Re-check
            </Button>
          )
        }
      />

      <Tabs
        label="Integrations"
        value={tab}
        onChange={setTab}
        className="mb-5"
        tabs={[
          {
            value: "apps",
            label: (
              <>
                Connected apps <Badge tone="neutral">MCP</Badge>
              </>
            ),
            icon: <IconPlug size={15} />,
          },
          { value: "services", label: "Services", icon: <IconSettings size={15} /> },
        ]}
      />

      <div role="tabpanel" aria-label={tab === "apps" ? "Connected apps" : "Services"}>
        {tab === "apps" ? <ConnectedApps connect={connect} onConnect={setConnect} /> : <Services onRetry={refresh} />}
      </div>
    </Page>
  );
}

/** The server's own wiring — environment variables and what each unlocks. */
function Services({ onRetry }: { onRetry: () => void }) {
  const { health, error } = useHealth();
  const auth = useAuth();
  const authOn = health?.auth_enabled ?? auth.enabled;

  return (
    <>
      {error && !health && (
        <div className="mb-4">
          <ErrorNote title="Couldn't reach the server" message={error} onRetry={onRetry} />
        </div>
      )}

      {!health ? (
        !error && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-40 rounded-xl" />
            ))}
          </div>
        )
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Connected" value={health.live.length} hint="Integrations with credentials" />
            <Stat label="Not configured" value={health.mocked.length} hint="Running on mocks or off" accent={health.mocked.length > 0} />
            <Stat
              label="Mode"
              value={<span className="font-sans capitalize">{health.telephony_mode}</span>}
              hint={health.provider_label ? `Model: ${health.provider_label}` : "No model provider"}
            />
          </div>

          <Callout tone="info">{health.note}</Callout>

          {/* Access control */}
          <Card>
            <CardHeader title="Access" subtitle="Who can open this console and place calls." icon={<IconLock size={16} />} />
            <div className="flex items-start gap-3 px-5 py-4">
              <span className={cx("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", authOn ? "bg-good/12 text-good" : "bg-warning/12 text-warning")}>
                <IconShield size={16} />
              </span>
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-medium text-ink">{authOn ? "Password protected" : "Open to anyone with the link"}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">
                  {authOn
                    ? "Every API call and live stream needs a session. Sessions expire after AUTH_TOKEN_TTL_HOURS (12 by default)."
                    : "Set ADMIN_PASSWORD on the server and restart to require a password. Optionally set AUTH_SECRET to keep sessions valid across password changes."}
                </p>
              </div>
              <Badge tone={authOn ? "good" : "warning"}>{authOn ? "On" : "Off"}</Badge>
            </div>
          </Card>

          {GROUPS.map((group) => (
            <Card key={group.title} className="overflow-hidden">
              <CardHeader title={group.title} subtitle={group.subtitle} />
              <ul className="divide-y divide-line">
                {group.items.map((item) => {
                  const live = health.checks[item.key] === true;
                  return (
                    <li key={item.key} className="flex items-start gap-4 px-5 py-4">
                      <span className={cx("mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", live ? "bg-good/12 text-good" : "bg-subtle text-ink-muted")}>
                        {item.icon}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-semibold text-ink">{item.label}</h3>
                          {live ? (
                            <Badge tone="good" icon={<IconCheck size={11} />}>
                              Connected
                            </Badge>
                          ) : (
                            <Badge tone="neutral">Not configured</Badge>
                          )}
                        </div>
                        <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">{item.description}</p>
                        {!live && (
                          <p className="mt-2 rounded-md font-mono border border-line bg-subtle/60 px-3 py-2 text-2xs leading-relaxed text-ink-secondary">
                            {item.configHint}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          ))}

          {health.provider && health.providers_configured.length > 1 && (
            <p className="text-xs text-ink-muted">
              Also configured: {health.providers_configured.filter((p) => p !== health.provider).join(", ")}. The active provider is{" "}
              {health.provider_label}.
            </p>
          )}
        </div>
      )}
    </>
  );
}
