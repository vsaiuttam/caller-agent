import { api } from "../api";
import {
  IconBlock,
  IconCampaign,
  IconChip,
  IconClock,
  IconCoin,
  IconPhone,
} from "../components/icons";
import {
  Card,
  LiveDot,
  Skeleton,
} from "../components/ui";
import { usePolling } from "../hooks";
import type { ReactNode } from "react";

const INTEGRATION_META: Record<
  string,
  { label: string; description: string; icon: ReactNode; configHint: string }
> = {
  database: {
    label: "Database",
    description: "PostgreSQL for persistent storage of campaigns, calls, and contacts.",
    icon: <IconCoin size={18} />,
    configHint: "Set DATABASE_URL in Render environment variables.",
  },
  model_provider: {
    label: "AI Model Provider",
    description: "LLM for conversation and extraction (Gemini, Claude, or OpenAI).",
    icon: <IconChip size={18} />,
    configHint: "Set GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY.",
  },
  telephony: {
    label: "Telephony",
    description: "PSTN calling via Twilio or Telnyx for placing real phone calls.",
    icon: <IconPhone size={18} />,
    configHint: "Set TELEPHONY=twilio and provide TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER.",
  },
  sms: {
    label: "SMS Follow-up",
    description: "Text the person after each call via Twilio, with delivery receipts.",
    icon: <IconCampaign size={18} />,
    configHint: "Uses Twilio credentials. Enable per-campaign under Follow-up messages.",
  },
  whatsapp: {
    label: "WhatsApp Follow-up",
    description: "WhatsApp the person after each call via Twilio, with delivered/read receipts.",
    icon: <IconCampaign size={18} />,
    configHint:
      "Set TWILIO_WHATSAPP_FROM (Sandbox: +14155238886). Outside the Sandbox, also set TWILIO_WHATSAPP_CONTENT_SID to an approved template.",
  },
  calendar: {
    label: "Google Calendar",
    description: "Automatically book appointments on a shared Google Calendar after calls.",
    icon: <IconClock size={18} />,
    configHint: "Set GOOGLE_CALENDAR_ID and GOOGLE_CREDENTIALS_PATH with a service account JSON.",
  },
  records_api: {
    label: "Records / CRM API",
    description: "Sync call outcomes and collected fields to your internal CRM or ATS.",
    icon: <IconCoin size={18} />,
    configHint: "Set RECORDS_API_URL and RECORDS_API_KEY pointing to your CRM endpoint.",
  },
  webhook_signing: {
    label: "Webhook Signing",
    description: "HMAC-SHA256 signatures on outbound webhooks so receivers can verify authenticity.",
    icon: <IconBlock size={18} />,
    configHint: "Set WEBHOOK_SIGNING_SECRET in Render. Share the same secret with your webhook receiver.",
  },
  speech_to_text: {
    label: "Speech-to-Text",
    description: "Transcribes caller speech. Twilio provides this built-in; Deepgram for LiveKit mode.",
    icon: <IconChip size={18} />,
    configHint: "Built-in with Twilio. For LiveKit, set DEEPGRAM_API_KEY.",
  },
  text_to_speech: {
    label: "Text-to-Speech",
    description: "Converts AI responses to natural voice. Twilio uses Polly Neural; Cartesia for LiveKit.",
    icon: <IconChip size={18} />,
    configHint: "Built-in with Twilio (Polly Neural). For LiveKit, set CARTESIA_API_KEY.",
  },
};

const PRIORITY_ORDER = [
  "database",
  "model_provider",
  "telephony",
  "sms",
  "whatsapp",
  "speech_to_text",
  "text_to_speech",
  "calendar",
  "records_api",
  "webhook_signing",
];

export default function Settings() {
  const health = usePolling(() => api.health(), 30_000).data;

  return (
    <div className="px-6 py-5">
      <header className="mb-5">
        <h1 className="text-xl font-bold tracking-tight">Integrations</h1>
        <p className="mt-0.5 text-sm text-ink-muted">
          Status of all connected services. Configure via environment variables on Render.
        </p>
      </header>

      {!health ? (
        <div className="space-y-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : (
        <>
          {/* Summary */}
          <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Card className="px-4 py-3">
              <p className="text-[11px] font-medium text-ink-muted">Connected</p>
              <p className="tnum mt-1 text-2xl font-bold text-good">
                {health.live.length}
              </p>
            </Card>
            <Card className="px-4 py-3">
              <p className="text-[11px] font-medium text-ink-muted">Mocked / Off</p>
              <p className="tnum mt-1 text-2xl font-bold text-warning">
                {health.mocked.length}
              </p>
            </Card>
            <Card className="px-4 py-3">
              <p className="text-[11px] font-medium text-ink-muted">Mode</p>
              <p className="mt-1 text-lg font-bold capitalize">
                {health.telephony_mode}
              </p>
            </Card>
          </div>

          {/* Integration list */}
          <div className="space-y-2">
            {PRIORITY_ORDER.map((key) => {
              const meta = INTEGRATION_META[key];
              if (!meta) return null;
              const isLive = health.checks[key] === true;

              return (
                <Card key={key} className="flex items-start gap-4 px-5 py-4">
                  <div className={`mt-0.5 rounded-lg p-2 ${isLive ? "bg-good/10 text-good" : "bg-ink-muted/10 text-ink-muted"}`}>
                    {meta.icon}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-semibold">{meta.label}</h3>
                      {isLive ? (
                        <span className="flex items-center gap-1.5 rounded-md bg-good/10 px-2 py-0.5 text-[10px] font-medium text-good">
                          <LiveDot /> Connected
                        </span>
                      ) : (
                        <span className="rounded-md bg-warning/10 px-2 py-0.5 text-[10px] font-medium text-warning">
                          Not configured
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-ink-secondary">
                      {meta.description}
                    </p>
                    {!isLive && (
                      <p className="mt-1.5 rounded-md border border-[var(--surface-border)] bg-elevated px-3 py-2 text-[11px] text-ink-muted">
                        {meta.configHint}
                      </p>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>

          {/* Provider info */}
          {health.provider && (
            <div className="mt-5">
              <Card className="px-5 py-4">
                <h3 className="text-sm font-semibold">Active Model Provider</h3>
                <p className="mt-1 text-xs text-ink-secondary">
                  <span className="font-medium text-ink">{health.provider_label}</span>{" "}
                  ({health.provider})
                </p>
                {health.providers_configured.length > 1 && (
                  <p className="mt-1 text-[11px] text-ink-muted">
                    Also configured: {health.providers_configured.filter(p => p !== health.provider).join(", ")}
                  </p>
                )}
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  );
}
