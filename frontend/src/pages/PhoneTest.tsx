/**
 * Test lab → Call a phone. The agent rings a real number (yours) and you
 * watch the call in the live console as it happens.
 *
 * POST /api/test-call answers 202 with a call_id before dialling; everything
 * after that streams over /api/events (see components/live).
 */

import { useState } from "react";
import { ApiError, api } from "../api";
import { CallConsole, type CallPhase } from "../components/live/CallConsole";
import { IconPhone } from "../components/icons";
import { Button, Callout, Card, CardHeader, EmptyState, Field, Input, Switch, toast } from "../components/ui";
import { useHealth } from "../data";
import { useLocalStorage } from "../hooks";
import { CampaignField, useTestLab } from "./TestLab";

const E164 = /^\+[1-9]\d{6,14}$/;
const normalise = (raw: string) => raw.replace(/[\s\-().]/g, "");

export default function PhoneTest() {
  const { campaignId, campaign } = useTestLab();
  const { health } = useHealth();
  const [phone, setPhone] = useLocalStorage("samvaad.testPhone", "");
  const [touched, setTouched] = useState(false);
  const [contactName, setContactName] = useState("Alex Morgan");
  const [sendSms, setSendSms] = useState(true);
  const [sendWhatsapp, setSendWhatsapp] = useState(true);
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [call, setCall] = useState<{ id: string; startedAt: number } | null>(null);
  const [phase, setPhase] = useState<CallPhase | null>(null);

  const number = normalise(phone);
  const valid = E164.test(number);
  const inProgress = !!call && phase !== "done" && phase !== "failed";
  const telephonyReady =
    !health || (["twilio", "telnyx"].includes(health.telephony_mode.toLowerCase()) && health.checks.telephony !== false);
  const modelReady = !health || health.can_run_simulations;
  const canCall = !!campaignId && valid && !placing && !inProgress && telephonyReady && modelReady;

  const place = async () => {
    if (!canCall) return;
    setPlacing(true);
    setError(null);
    try {
      const accepted = await api.startTestCall({
        campaign_id: campaignId,
        contact_name: contactName,
        phone_number: number,
        send_sms: sendSms,
        send_whatsapp: sendWhatsapp,
      });
      setPhase("dialing");
      setCall({ id: accepted.call_id, startedAt: Date.now() });
      toast.success(`Calling ${number}`, "Your phone should ring in a few seconds.");
    } catch (err) {
      const message =
        err instanceof ApiError && err.status === 422 ? "That number isn't in international format (+ and country code)." : (err as Error).message;
      setError(message);
      toast.error("Couldn't place the call", message);
    } finally {
      setPlacing(false);
    }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)] lg:items-start">
      <Card className="lg:sticky lg:top-20">
        <CardHeader title="Setup" subtitle="A real call to a real phone — use your own number." />
        <form
          className="space-y-5 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            void place();
          }}
        >
          <CampaignField disabled={inProgress} />

          <Field
            label="Phone number"
            hint="International format, e.g. +919876543210 or +14155550123."
            error={touched && phone && !valid ? "Start with + and the country code, digits only." : null}
          >
            <Input
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              placeholder="+91 98765 43210"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={touched && !!phone && !valid}
              disabled={inProgress}
              className="tnum"
            />
          </Field>

          <Field label="Name to greet" hint="Substituted into {first_name} in the greeting.">
            <Input value={contactName} onChange={(e) => setContactName(e.target.value)} disabled={inProgress} />
          </Field>

          <div className="space-y-3 rounded-lg border border-line p-3.5">
            <p className="text-xs font-medium text-ink-secondary">After the call, message this number</p>
            <Switch checked={sendSms} onChange={setSendSms} disabled={inProgress} label="SMS" />
            <Switch
              checked={sendWhatsapp}
              onChange={setSendWhatsapp}
              disabled={inProgress}
              label="WhatsApp"
              description={
                health && sendWhatsapp && !health.checks.whatsapp
                  ? "Not configured on the server — set TWILIO_WHATSAPP_FROM."
                  : undefined
              }
            />
          </div>

          <Button
            type="submit"
            size="lg"
            className="w-full"
            loading={placing}
            disabled={!canCall}
            icon={<IconPhone size={15} />}
          >
            {placing ? "Placing the call…" : inProgress ? "Call in progress" : call ? "Call again" : "Call me"}
          </Button>
          {!campaignId && <p className="-mt-2 text-center text-xs text-ink-muted">Pick a campaign to call about.</p>}
        </form>
      </Card>

      <div className="min-w-0 space-y-3">
        {health && !modelReady && (
          <Callout tone="warning" title="No model provider is configured">
            Set a provider key on the server — the agent has nothing to think with yet.
          </Callout>
        )}
        {health && modelReady && !telephonyReady && (
          <Callout tone="warning" title="Real calls need a phone carrier">
            The server is in <span className="font-medium capitalize">{health.telephony_mode}</span> mode. Set{" "}
            <code className="font-mono text-2xs">TELEPHONY=twilio</code> (or <code className="font-mono text-2xs">telnyx</code>) with its
            credentials and restart. Simulated calls and the browser mic work without it.
          </Callout>
        )}
        {error && !call && (
          <Callout tone="critical" title="The call wasn't placed">
            {error}
          </Callout>
        )}

        {call ? (
          <CallConsole
            key={call.id}
            callId={call.id}
            startedAt={call.startedAt}
            mode="test"
            onPhaseChange={setPhase}
            onRetry={canCall ? () => void place() : undefined}
          />
        ) : (
          <Card>
            <EmptyState
              title="Ring your own phone"
              hint={
                campaign
                  ? `The agent will call you about “${campaign.name}”. Watch it here as it happens — transcript, reply times, and the outcome the moment you hang up.`
                  : "Pick a campaign and enter your number. You'll watch the conversation here as it happens — transcript, reply times, and the outcome the moment you hang up."
              }
            />
          </Card>
        )}
      </div>
    </div>
  );
}
