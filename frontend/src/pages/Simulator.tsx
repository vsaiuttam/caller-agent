/**
 * Test lab → Simulated caller. A model plays the person; nobody is called
 * and nothing is dispatched.
 */

import { useState } from "react";
import { api, type SimulationResult } from "../api";
import { AgentAvatar } from "../components/AgentAvatar";
import CallResult from "../components/CallResult";
import { IconCheck, IconPlay } from "../components/icons";
import {
  Button,
  Callout,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Skeleton,
  Switch,
  cx,
  dispositionLabel,
  toast,
} from "../components/ui";
import { useHealth } from "../data";
import { useAsync } from "../hooks";
import { CampaignField, useTestLab } from "./TestLab";

export default function Simulator() {
  const { campaignId, campaign } = useTestLab();
  const { health } = useHealth();
  const personas = useAsync(() => api.personas(), []);

  const [persona, setPersona] = useState("cooperative");
  const [contactName, setContactName] = useState("Alex Morgan");
  const [exchanges, setExchanges] = useState(8);
  const [save, setSave] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canRun = !!campaignId && !running;

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const outcome = await api.simulate({
        campaign_id: campaignId,
        persona,
        contact_name: contactName,
        max_exchanges: exchanges,
        save,
      });
      setResult(outcome);
      toast.success(
        `Simulation finished — ${dispositionLabel(outcome.outcome.disposition)}`,
        save ? "Saved to the call log as a test call." : undefined,
      );
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      toast.error("The simulation failed", message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)] lg:items-start">
      <Card className="lg:sticky lg:top-20">
        <CardHeader title="Setup" subtitle="Nobody is called. Nothing is dispatched." />
        <div className="space-y-5 p-5">
          <CampaignField disabled={running} />

          <Field label="Who answers" group>
            <div className="space-y-1.5" role="radiogroup" aria-label="Persona">
              {personas.loading
                ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full" />)
                : (personas.data ?? []).map((p) => {
                    const active = p.id === persona;
                    return (
                      <button
                        key={p.id}
                        type="button"
                        role="radio"
                        aria-checked={active}
                        onClick={() => setPersona(p.id)}
                        disabled={running}
                        className={cx(
                          "w-full rounded-lg border px-3.5 py-2.5 text-left transition-colors duration-150",
                          active ? "border-brand/50 bg-brand/8" : "border-line hover:border-line-strong hover:bg-subtle/60",
                        )}
                      >
                        <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
                          {active && <IconCheck size={13} className="text-brand" />}
                          {p.name}
                        </span>
                        <span className="mt-0.5 block text-xs leading-relaxed text-ink-muted">{p.description}</span>
                      </button>
                    );
                  })}
            </div>
          </Field>

          <Field label="Their name" hint="Substituted into {first_name} in the greeting.">
            <Input value={contactName} onChange={(e) => setContactName(e.target.value)} disabled={running} />
          </Field>

          <Field label={`Stop after ${exchanges} exchanges`} hint="Two models talking won't hang up on each other. This is the stop.">
            <input
              type="range"
              min={2}
              max={20}
              value={exchanges}
              onChange={(e) => setExchanges(Number(e.target.value))}
              disabled={running}
              className="w-full"
            />
          </Field>

          <Switch
            checked={save}
            onChange={setSave}
            disabled={running}
            label="Keep this run"
            description="Saves it to the call log, flagged as a test. Never counted in metrics."
          />

          <Button onClick={run} disabled={!canRun} loading={running} icon={<IconPlay size={13} />} size="lg" className="w-full">
            {running ? "Running the call…" : "Run simulated call"}
          </Button>
        </div>
      </Card>

      <div className="min-w-0 space-y-3">
        {health && !health.can_run_simulations && (
          <Callout tone="warning" title="No model provider is configured">
            Set a provider key (Gemini, Anthropic or OpenAI) on the server and restart it — there's nothing to talk to yet.
          </Callout>
        )}
        {error && !running && (
          <Callout
            tone="critical"
            title="The simulation failed"
            action={<Button size="sm" variant="secondary" onClick={run} disabled={!canRun}>Try again</Button>}
          >
            {error}
          </Callout>
        )}

        {running && (
          <Card className="p-5" aria-busy="true">
            <div className="flex items-center gap-4">
              <AgentAvatar state="speaking" size="md" />
              <div>
                <p className="text-sm font-semibold text-ink">Talking to {contactName || "them"}…</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                  Each exchange is two model round-trips. Eight exchanges take around half a minute.
                </p>
              </div>
            </div>
            <div className="mt-5 space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className={cx("h-11 rounded-2xl", i % 2 ? "ml-auto w-3/5" : "w-2/3")} />
              ))}
            </div>
          </Card>
        )}

        {!running && !result && !error && (
          <Card>
            <EmptyState
              title="No test run yet"
              hint={
                campaign
                  ? `Ready to run “${campaign.name}” against the ${persona.replace(/_/g, " ")} persona.`
                  : "Pick a campaign, choose who answers, and run it. You'll get the transcript, the scorecard and what the extractor wrote."
              }
            />
          </Card>
        )}

        {result && (
          <CallResult
            result={result}
            personName={contactName || "Person"}
            footnotes={[
              `On the call: ${result.conversation_model}`,
              `After: ${result.extraction_model}`,
              result.persona ? `Persona: ${result.persona.replace(/_/g, " ")}` : "Simulated",
            ]}
          />
        )}
      </div>
    </div>
  );
}
