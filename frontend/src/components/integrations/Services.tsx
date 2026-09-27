/**
 * Server-configured services (environment variables, then a restart): what
 * each one unlocks, whether it's connected, and exactly what to set when it
 * isn't. Integrations shows them by area; Settings shows the core ones.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useHealth } from "../../data";
import { IconBlock, IconCalendar, IconCampaign, IconCheck, IconChip, IconCoin, IconMic, IconPhone, IconWhisper } from "../icons";
import { Badge, Card, CardHeader, ErrorNote, Skeleton, cx } from "../ui";

export interface Service {
  key: string;
  label: string;
  description: string;
  icon: ReactNode;
  configHint: ReactNode;
}

export const SERVICES: Record<string, Service> = {
  database: {
    key: "database",
    label: "Database",
    description: "Stores campaigns, contacts and every call.",
    icon: <IconCoin size={17} />,
    configHint: "Set DATABASE_URL.",
  },
  model_provider: {
    key: "model_provider",
    label: "Model provider",
    description: "The LLM for the conversation and the post-call extraction.",
    icon: <IconChip size={17} />,
    configHint: (
      <>
        Add one on{" "}
        <Link to="/app/ai-models?add=1" className="font-sans font-medium text-brand hover:underline">
          AI models
        </Link>
        , or set an API key such as GEMINI_API_KEY on the server.
      </>
    ),
  },
  telephony: {
    key: "telephony",
    label: "Telephony",
    description: "Places real phone calls through Twilio or Telnyx.",
    icon: <IconPhone size={17} />,
    configHint: "Set TELEPHONY=twilio with TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER (or the Telnyx equivalents), then restart.",
  },
  speech_to_text: {
    key: "speech_to_text",
    label: "Speech-to-text",
    description: "Transcribes the person. Built into Twilio; Sarvam for Indian languages; Deepgram for LiveKit.",
    icon: <IconMic size={17} />,
    configHint: "Built in with Twilio. Otherwise set SARVAM_API_KEY or DEEPGRAM_API_KEY.",
  },
  text_to_speech: {
    key: "text_to_speech",
    label: "Text-to-speech",
    description: "The agent's voice. Sarvam for Indian languages and voice previews, Twilio Polly, or Cartesia.",
    icon: <IconWhisper size={17} />,
    configHint: "Set SARVAM_API_KEY for Indian voices and previews. Otherwise CARTESIA_API_KEY, or Twilio's built-in voice.",
  },
  sms: {
    key: "sms",
    label: "SMS",
    description: "Heads-up messages before calls and follow-ups after, with delivery receipts.",
    icon: <IconCampaign size={17} />,
    configHint: "Uses the Twilio credentials and number. In India, register message templates on DLT with your operator.",
  },
  whatsapp: {
    key: "whatsapp",
    label: "WhatsApp",
    description: "Heads-up and follow-up messages on WhatsApp, with delivered and read receipts.",
    icon: <IconCampaign size={17} />,
    configHint: "Set TWILIO_WHATSAPP_FROM (Sandbox: +14155238886). Outside the Sandbox also set TWILIO_WHATSAPP_CONTENT_SID for an approved template.",
  },
  calendar: {
    key: "calendar",
    label: "Calendar",
    description: "Books agreed appointments on a shared calendar.",
    icon: <IconCalendar size={17} />,
    configHint: "Set GOOGLE_CALENDAR_CREDENTIALS, or BUILTIN_CALENDAR=1 for the built-in one.",
  },
  records_api: {
    key: "records_api",
    label: "Records / CRM",
    description: "Writes collected fields to your CRM or ATS.",
    icon: <IconCoin size={17} />,
    configHint: "Set RECORDS_API_URL (and RECORDS_API_KEY), or BUILTIN_RECORDS=1. For richer CRMs, connect them as an app over MCP.",
  },
  webhook_signing: {
    key: "webhook_signing",
    label: "Webhook signing",
    description: "HMAC-SHA256 signatures on each campaign's webhook, so receivers can verify us. Webhook URLs are set per campaign.",
    icon: <IconBlock size={17} />,
    configHint: "Set WEBHOOK_SIGNING_SECRET and share it with the receiver.",
  },
};

/** One group of services, each with its status and, when missing, what to set. */
export function ServiceGroup({ title, subtitle, keys }: { title: string; subtitle?: string; keys: string[] }) {
  const { health, error, reload } = useHealth();

  if (!health) {
    return error ? <ErrorNote title="Couldn't reach the server" message={error} onRetry={reload} /> : <Skeleton className="h-48 rounded-xl" />;
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader title={title} subtitle={subtitle} />
      <ul className="divide-y divide-line">
        {keys.map((key) => {
          const item = SERVICES[key];
          if (!item) return null;
          const live = health.checks[key] === true;
          return (
            <li key={key} className="flex items-start gap-4 px-5 py-4">
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
                    <Badge tone="neutral">Not set up</Badge>
                  )}
                </div>
                <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">{item.description}</p>
                {!live && (
                  <p className="mt-2 rounded-md border border-line bg-subtle/60 px-3 py-2 font-mono text-2xs leading-relaxed text-ink-secondary">{item.configHint}</p>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
