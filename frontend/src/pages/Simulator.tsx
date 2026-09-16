/**
 * Rehearse a call before dialling anybody.
 */

import { useState } from "react";
import {
  api,
  type Campaign,
  type Persona,
  type SimulationResult,
} from "../api";
import {
  IconBolt,
  IconCheck,
  IconCoin,
  IconFlask,
  IconPhone,
  IconPlay,
  IconShield,
} from "../components/icons";
import OutcomeCard from "../components/OutcomeCard";
import { ScorecardResult } from "../components/Scorecard";
import {
  Button,
  Card,
  CardHeader,
  DispositionBadge,
  EmptyState,
  ErrorNote,
  Field,
  PageWrapper,
  Skeleton,
  inputClass,
} from "../components/ui";
import { useAsync } from "../hooks";

export default function Simulator() {
  const campaigns = useAsync(() => api.campaigns(), []);
  const personas = useAsync(() => api.personas(), []);
  const health = useAsync(() => api.health(), []);

  const [campaignId, setCampaignId] = useState("");
  const [persona, setPersona] = useState("cooperative");
  const [contactName, setContactName] = useState("Alex Morgan");
  const [exchanges, setExchanges] = useState(8);
  const [save, setSave] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState("");

  const [running, setRunning] = useState(false);
  const [calling, setCalling] = useState(false);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const campaign: Campaign | undefined = campaigns.data?.find((c) => c.id === campaignId);
  const canRun = !!campaignId && !running && !calling;
  const canCall =
    !!campaignId &&
    !running &&
    !calling &&
    /^\+[1-9]\d{6,14}$/.test(phoneNumber);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await api.simulate({
          campaign_id: campaignId,
          persona,
          contact_name: contactName,
          max_exchanges: exchanges,
          save,
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const callMe = async () => {
    setCalling(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await api.testCall({
          campaign_id: campaignId,
          persona,
          contact_name: contactName,
          max_exchanges: exchanges,
          save,
          phone_number: phoneNumber,
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCalling(false);
    }
  };

  return (
    <PageWrapper className="mx-auto max-w-[1180px] px-6 py-5">
      <header className="mb-5">
        <h1 className="flex items-center gap-2.5 text-xl font-bold tracking-tight">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand/15 text-brand">
            <IconFlask size={18} />
          </span>
          Test calls
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-muted">
          Run a campaign against a simulated person. Same prompt, same models,
          same extractor — only the phone line is fake.
        </p>
      </header>

      {health.data && !health.data.can_run_simulations && (
        <div className="mb-4">
          <ErrorNote message="No model provider is configured. Set a provider key in .env and restart the server." />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[380px_1fr] lg:items-start">
        {/* Setup */}
        <Card hover={false}>
          <CardHeader title="Setup" subtitle="Nobody is called. Nothing is dispatched." />
          <div className="space-y-4 p-5">
            <Field
              label="Campaign"
              hint="Its goal, greeting, constraints, language, and model choice are all used as-is."
            >
              {campaigns.loading ? (
                <Skeleton className="mt-1 h-10 w-full" />
              ) : (
                <select
                  value={campaignId}
                  onChange={(e) => setCampaignId(e.target.value)}
                  className={inputClass}
                >
                  <option value="">Choose a campaign\u2026</option>
                  {(campaigns.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>

            <div>
              <span className="text-xs font-semibold text-ink-secondary">
                Who answers
              </span>
              <div className="mt-2 space-y-1.5">
                {personas.loading
                  ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-14 w-full" />)
                  : (personas.data ?? []).map((p: Persona) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => setPersona(p.id)}
                        aria-pressed={p.id === persona}
                        className={`ripple w-full rounded-lg border px-4 py-3 text-left transition-colors duration-150 ${
                          p.id === persona
                            ? "border-brand/40 bg-brand/8"
                            : "border-white/10 hover:border-brand/20 hover:bg-elevated/50"
                        }`}
                      >
                        <span className="flex items-center gap-1.5 text-xs font-semibold">
                          {p.id === persona && (
                            <span className="text-brand">
                              <IconCheck size={12} />
                            </span>
                          )}
                          {p.name}
                        </span>
                        <span className="mt-0.5 block text-[11px] leading-relaxed text-ink-muted">
                          {p.description}
                        </span>
                      </button>
                    ))}
              </div>
            </div>

            <Field label="Their name" hint="Substituted into {first_name} in the greeting.">
              <input
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                className={inputClass}
              />
            </Field>

            <Field
              label={`Stop after ${exchanges} exchanges`}
              hint="Two models talking will not hang up on each other. This is the stop."
            >
              <input
                type="range"
                min={2}
                max={20}
                value={exchanges}
                onChange={(e) => setExchanges(Number(e.target.value))}
                className="mt-2 w-full accent-[var(--color-brand)]"
              />
            </Field>

            <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-white/10 px-3.5 py-3">
              <input
                type="checkbox"
                checked={save}
                onChange={(e) => setSave(e.target.checked)}
                className="mt-0.5 accent-[var(--color-brand)]"
              />
              <span className="text-xs">
                <span className="font-semibold">Keep this run</span>
                <span className="mt-0.5 block leading-relaxed text-ink-muted">
                  Saves it to the calls list, flagged as a simulation.
                </span>
              </span>
            </label>

            <Button onClick={run} disabled={!canRun}>
              <IconPlay size={13} />
              {running ? "Running\u2026" : "Run simulated call"}
            </Button>

            <div className="border-t border-white/10 pt-4">
              <Field
                label="Or call a real phone"
                hint="Enter your phone number in E.164 format (e.g. +1234567890) to receive a real call from the AI agent."
              >
                <input
                  type="tel"
                  placeholder="+1234567890"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  className={inputClass}
                />
              </Field>
              <Button
                onClick={callMe}
                disabled={!canCall}
                variant="secondary"
              >
                <IconPhone size={13} />
                {calling ? "Calling\u2026" : "Call me"}
              </Button>
              {calling && (
                <p className="mt-2 text-xs text-ink-muted">
                  Your phone should ring shortly. The AI agent will speak using the campaign's greeting and configuration.
                </p>
              )}
            </div>

            {!campaignId && (
              <p className="text-xs text-ink-muted">Pick a campaign to run.</p>
            )}
          </div>
        </Card>

        {/* Result */}
        <div className="space-y-3">
          {error && <ErrorNote message={error} />}

          {running && (
            <Card className="p-5" hover={false}>
              <p className="text-sm font-semibold">
                Calling {contactName || "them"}\u2026
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                Each exchange is two model round-trips. Ten exchanges takes
                around half a minute.
              </p>
              <div className="mt-4 space-y-2">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton
                    key={i}
                    className={`h-10 ${i % 2 ? "ml-12" : "mr-12"}`}
                  />
                ))}
              </div>
            </Card>
          )}

          {!running && !result && !error && (
            <Card hover={false}>
              <EmptyState
                title="No test run yet"
                hint={
                  campaign
                    ? `Ready to run "${campaign.name}" against the ${persona.replace("_", " ")} persona.`
                    : "Pick a campaign on the left, choose who answers, and run it."
                }
              />
            </Card>
          )}

          {result && <Result result={result} />}
        </div>
      </div>
    </PageWrapper>
  );
}

// ---------------------------------------------------------------------------

function Result({ result }: { result: SimulationResult }) {
  const latency = result.median_first_chunk_ms;

  return (
    <>
      <div className="grid gap-2 sm:grid-cols-3">
        <Figure
          label="Median first audio"
          value={latency === null ? "\u2014" : `${latency} ms`}
          hint={
            latency === null
              ? "No agent turns to measure"
              : latency < 800
                ? "Feels immediate on a call"
                : "Audible pause \u2014 try a faster model"
          }
          tone={latency !== null && latency >= 800 ? "warning" : "neutral"}
          icon={<IconBolt size={15} />}
        />
        <Figure
          label="Cost of this call"
          value={`$${result.usage.cost_usd.toFixed(4)}`}
          hint={`${result.usage.input_tokens.toLocaleString()} in / ${result.usage.output_tokens.toLocaleString()} out`}
          icon={<IconCoin size={15} />}
        />
        <Figure
          label="Cache hit rate"
          value={`${Math.round(result.usage.cache_hit_rate * 100)}%`}
          hint="Prompt input served from cache"
          icon={<IconShield size={15} />}
        />
      </div>

      <Card hover={false}>
        <CardHeader
          title="Transcript"
          subtitle={`Ended because ${result.ended_because}.`}
          action={<DispositionBadge value={result.outcome.disposition} />}
        />
        <div className="space-y-3 p-5">
          {result.turns.map((turn, i) => {
            const agent = turn.role === "assistant";
            return (
              <div
                key={i}
                className={`flex flex-col ${agent ? "items-start" : "items-end"}`}
              >
                <div
                  className={`max-w-[80%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
                    agent ? "rounded-tl-sm bg-elevated" : "rounded-tr-sm bg-brand/12 text-ink"
                  }`}
                >
                  {turn.text}
                </div>
                <div className="mt-1 flex items-center gap-2 px-1 text-[11px] text-ink-muted">
                  <span className="font-medium">{agent ? "Agent" : "Person"}</span>
                  {turn.first_chunk_ms !== null && (
                    <>
                      <span>·</span>
                      <span className={`tnum ${turn.first_chunk_ms >= 800 ? "text-warning" : ""}`}>
                        {turn.first_chunk_ms} ms
                      </span>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <ScorecardResult
        scores={result.outcome.scores}
        qualification={result.qualification}
      />

      <OutcomeCard
        outcome={result.outcome}
        footnotes={[
          `On the call: ${result.conversation_model}`,
          `After: ${result.extraction_model}`,
          `Persona: ${result.persona.replace("_", " ")}`,
        ]}
      />
    </>
  );
}

function Figure({
  label,
  value,
  hint,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  tone?: "neutral" | "warning";
}) {
  return (
    <Card className={`px-4 py-3 ${tone === "warning" ? "!border-warning/30" : ""}`}>
      <div className="flex items-start justify-between">
        <p className="text-[11px] font-medium text-ink-muted">{label}</p>
        <span className={tone === "warning" ? "text-warning" : "text-ink-muted/60"}>
          {icon}
        </span>
      </div>
      <p className="tnum mt-1.5 text-xl font-bold leading-none">{value}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{hint}</p>
    </Card>
  );
}
