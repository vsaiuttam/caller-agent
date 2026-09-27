/**
 * Integrations: everything the agent connects to, moved out of Settings.
 *
 *   ?tab=apps (default)  connected apps over MCP; ?connect=1 opens the dialog
 *   ?tab=telephony       Twilio / Telnyx, speech-to-text, voices
 *   ?tab=messaging       SMS and WhatsApp (heads-ups and follow-ups)
 *   ?tab=webhooks        webhook signing, calendar, records
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { IconCampaign, IconPhone, IconPlug, IconPlus, IconRefresh } from "../components/icons";
import { ServiceGroup } from "../components/integrations/Services";
import type { ConnectIntent } from "../components/mcp/ConnectDialog";
import { ConnectedApps } from "../components/mcp/ConnectedApps";
import { Badge, Button, Callout, Page, PageHeader, Tabs } from "../components/ui";
import { useHealth } from "../data";
import { useDocumentTitle } from "../hooks";

type Tab = "apps" | "telephony" | "messaging" | "webhooks";

const DESCRIPTION: Record<Tab, string> = {
  apps: "Connect your own apps over MCP, so the agent can look things up during a call and record the outcome after it.",
  telephony: "How calls reach real phones, and how the agent hears and speaks. Configured with environment variables on the server, then a restart.",
  messaging: "SMS and WhatsApp, for heads-up messages before calls and follow-ups after them.",
  webhooks: "Where outcomes go when a call ends: signed webhooks, a calendar, your records system.",
};

const TITLE: Record<Tab, string> = { apps: "Connected apps", telephony: "Telephony", messaging: "Messaging", webhooks: "Webhooks" };

export default function Integrations() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab: Tab = requested === "telephony" || requested === "messaging" || requested === "webhooks" ? requested : "apps";
  useDocumentTitle(tab === "apps" ? "Integrations" : `${TITLE[tab]} · Integrations`);
  const { health, reload } = useHealth();
  const [connect, setConnect] = useState<ConnectIntent | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // ?connect=1 opens the dialog once, then drops the param so a reload doesn't reopen it.
  useEffect(() => {
    if (!params.has("connect")) return;
    setConnect("pick");
    const next = new URLSearchParams(params);
    next.delete("connect");
    next.delete("tab");
    setParams(next, { replace: true });
  }, [params, setParams]);

  const setTab = (value: Tab) => {
    const next = new URLSearchParams(params);
    if (value === "apps") next.delete("tab");
    else next.set("tab", value);
    setParams(next, { replace: true });
  };

  const recheck = () => {
    setRefreshing(true);
    reload();
    window.setTimeout(() => setRefreshing(false), 800);
  };

  const mode = health?.telephony_mode.toLowerCase() ?? "";

  return (
    <Page>
      <PageHeader
        icon={<IconPlug size={18} />}
        title="Integrations"
        description={DESCRIPTION[tab]}
        actions={
          tab === "apps" ? (
            <Button icon={<IconPlus size={14} />} onClick={() => setConnect("pick")}>
              Connect an app
            </Button>
          ) : (
            <Button variant="secondary" icon={<IconRefresh size={14} />} loading={refreshing} onClick={recheck}>
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
                Apps <Badge tone="neutral">MCP</Badge>
              </>
            ),
            icon: <IconPlug size={15} />,
          },
          { value: "telephony", label: "Telephony", icon: <IconPhone size={15} /> },
          { value: "messaging", label: "Messaging", icon: <IconCampaign size={15} /> },
          { value: "webhooks", label: "Webhooks" },
        ]}
      />

      <div role="tabpanel" aria-label={TITLE[tab]} className="space-y-4">
        {tab === "apps" && <ConnectedApps connect={connect} onConnect={setConnect} />}
        {tab === "telephony" && (
          <>
            {health && (
              <Callout tone={health.can_place_calls ? "good" : "warning"} title={health.can_place_calls ? `Calls go out through ${cap(mode)}` : "Real calls are off"}>
                {health.can_place_calls
                  ? "Test calls and campaigns ring real phones."
                  : "Telephony is mocked: rehearsals in the test lab work, but campaigns can't reach anyone until Twilio or Telnyx is configured below."}
              </Callout>
            )}
            <ServiceGroup title="Calls" subtitle="The carrier that dials." keys={["telephony"]} />
            <ServiceGroup title="Voice" subtitle="How the agent hears and speaks. Sarvam covers the Indian languages and voice previews." keys={["speech_to_text", "text_to_speech"]} />
          </>
        )}
        {tab === "messaging" && <ServiceGroup title="Messages" subtitle="Turned on per campaign: heads-ups in Schedule and messages, follow-ups after the call." keys={["sms", "whatsapp"]} />}
        {tab === "webhooks" && <ServiceGroup title="After the call" subtitle="Where outcomes go once the call ends." keys={["webhook_signing", "calendar", "records_api"]} />}
      </div>
    </Page>
  );
}

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : "the carrier");
