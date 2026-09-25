/**
 * Model selection: a call bills two models with opposite priorities, so
 * each role is chosen separately, and the estimator shows what a campaign
 * would cost with the current picks.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type EffortOption, type ModelDefaults, type ModelRole, type ModelSpec } from "../api";
import { IconBolt, IconCheck, IconChip, IconClock, IconCoin, IconUsers } from "../components/icons";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorNote,
  Eyebrow,
  Field,
  Input,
  Page,
  PageHeader,
  Segmented,
  Skeleton,
  cx,
  toast,
} from "../components/ui";
import { formatUsd } from "../format";
import { useAsync, useDocumentTitle } from "../hooks";

const SPEED_LABEL: Record<ModelSpec["speed"], string> = {
  fastest: "Fastest",
  fast: "Fast",
  balanced: "Balanced",
  deliberate: "Deliberate",
};

const SPEED_SWATCH: Record<ModelSpec["speed"], string> = {
  fastest: "bg-ramp-1",
  fast: "bg-ramp-2",
  balanced: "bg-ramp-3",
  deliberate: "bg-ramp-4",
};

const ROLE_COPY: Record<ModelRole, { title: string; subtitle: string; icon: ReactNode }> = {
  conversation: {
    title: "On the call",
    subtitle: "Runs live while someone is on the line. Latency is the whole game — every 100 ms is heard.",
    icon: <IconBolt size={16} />,
  },
  extraction: {
    title: "After the call",
    subtitle: "Reads the transcript and writes the record. Latency is free here; being wrong is not.",
    icon: <IconCheck size={16} />,
  },
};

export default function Models() {
  useDocumentTitle("Models");
  const catalog = useAsync(() => api.models(), []);
  const [draft, setDraft] = useState<ModelDefaults | null>(null);
  const [saving, setSaving] = useState(false);

  const current: ModelDefaults | null = draft ?? catalog.data?.defaults ?? null;
  const dirty = !!draft && !!catalog.data && JSON.stringify(draft) !== JSON.stringify(catalog.data.defaults);

  const update = (patch: Partial<ModelDefaults>) => {
    if (current) setDraft({ ...current, ...patch });
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await api.saveModelDefaults(draft);
      toast.success("Defaults saved", "New campaigns inherit these. Existing campaigns keep their own picks.");
      catalog.reload();
      setDraft(null);
    } catch (err) {
      toast.error("Couldn't save the defaults", (err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Page width="wide">
      <PageHeader
        icon={<IconChip size={18} />}
        title="Models"
        meta={catalog.data?.provider_label && <Badge tone="info">{catalog.data.provider_label}</Badge>}
        description="A call bills two models with opposite priorities. Assign each one separately — new campaigns inherit these."
        actions={
          <>
            {dirty && (
              <Button variant="ghost" onClick={() => setDraft(null)} disabled={saving}>
                Discard
              </Button>
            )}
            <Button onClick={save} disabled={!dirty} loading={saving}>
              Save as default
            </Button>
          </>
        }
      />

      {catalog.error && (
        <div className="mb-4">
          <ErrorNote message={catalog.error} onRetry={catalog.reload} />
        </div>
      )}

      {catalog.loading || !catalog.data || !current ? (
        <div className="space-y-3">
          <Skeleton className="h-56 w-full rounded-xl" />
          <Skeleton className="h-56 w-full rounded-xl" />
        </div>
      ) : (
        <div className="space-y-8">
          {catalog.data.roles.map((role) => (
            <RoleSection
              key={role}
              role={role}
              models={catalog.data!.models.filter((m) => m.roles.includes(role))}
              efforts={catalog.data!.efforts}
              selectedModel={role === "conversation" ? current.conversation_model : current.extraction_model}
              selectedEffort={role === "conversation" ? current.conversation_effort : current.extraction_effort}
              onModel={(id) => update(role === "conversation" ? { conversation_model: id } : { extraction_model: id })}
              onEffort={(value) => update(role === "conversation" ? { conversation_effort: value } : { extraction_effort: value })}
            />
          ))}

          <Estimator selection={current} pricingAsOf={catalog.data.pricing_as_of} />
        </div>
      )}
    </Page>
  );
}

// ---------------------------------------------------------------------------

function RoleSection({
  role,
  models,
  efforts,
  selectedModel,
  selectedEffort,
  onModel,
  onEffort,
}: {
  role: ModelRole;
  models: ModelSpec[];
  efforts: EffortOption[];
  selectedModel: string;
  selectedEffort: string;
  onModel: (id: string) => void;
  onEffort: (value: string) => void;
}) {
  const copy = ROLE_COPY[role];
  return (
    <section aria-labelledby={`role-${role}`}>
      <div className="mb-3 flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand/12 text-brand">{copy.icon}</span>
        <div>
          <h2 id={`role-${role}`} className="text-base font-semibold tracking-tight text-ink">
            {copy.title}
          </h2>
          <p className="mt-0.5 text-sm text-ink-secondary">{copy.subtitle}</p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" role="radiogroup" aria-labelledby={`role-${role}`}>
        {models.map((model) => (
          <ModelCard key={model.id} model={model} selected={model.id === selectedModel} onSelect={() => onModel(model.id)} />
        ))}
      </div>

      <Card className="mt-3 px-4 py-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <Eyebrow>Thinking effort</Eyebrow>
          <Segmented
            label={`${copy.title} thinking effort`}
            size="sm"
            value={selectedEffort}
            onChange={onEffort}
            options={efforts.map((effort) => ({
              value: effort.value,
              title: effort.description,
              label: (
                <>
                  {effort.label}
                  <span className="tnum text-ink-muted">×{effort.output_multiplier.toFixed(1)}</span>
                </>
              ),
            }))}
          />
        </div>
        <p className="mt-2 text-xs text-ink-muted">{efforts.find((e) => e.value === selectedEffort)?.description}</p>
      </Card>
    </section>
  );
}

function ModelCard({ model, selected, onSelect }: { model: ModelSpec; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cx(
        "card card-interactive flex h-full flex-col p-4 text-left",
        selected && "!border-brand/60 ring-2 ring-brand/15",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="flex items-center gap-2">
          <IconChip size={16} className={selected ? "text-brand" : "text-ink-muted"} />
          <span className="text-sm font-semibold tracking-tight text-ink">{model.name}</span>
        </span>
        {selected && (
          <Badge tone="brand" icon={<IconCheck size={11} />}>
            In use
          </Badge>
        )}
      </div>

      <p className="mt-2 text-xs leading-relaxed text-ink-secondary">{model.tagline}</p>

      <div className="mt-2.5 flex items-center gap-1.5 text-xs text-ink-muted">
        <span className={cx("inline-block h-2 w-2 rounded-full", SPEED_SWATCH[model.speed])} />
        <span>{SPEED_LABEL[model.speed]}</span>
        <span>·</span>
        <span className="tnum">{(model.context_tokens / 1000).toLocaleString()}K context</span>
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-2 rounded-lg bg-subtle px-3 py-2 text-xs">
        {(
          [
            ["Input", model.input_per_mtok],
            ["Output", model.output_per_mtok],
            ["Cached", model.cache_read_per_mtok],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt className="text-2xs font-medium text-ink-muted">{label}</dt>
            <dd className="tnum font-semibold text-ink">${value.toFixed(2)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-1 text-[10px] text-ink-muted">per million tokens</p>

      <ul className="mt-2.5 space-y-1">
        {model.strengths.slice(0, 3).map((s) => (
          <li key={s} className="flex gap-1.5 text-xs leading-relaxed text-ink-secondary">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand" />
            {s}
          </li>
        ))}
      </ul>

      {model.watch_out && (
        <p className="mt-2.5 rounded-lg border border-warning/25 bg-warning/6 px-3 py-2 text-2xs leading-relaxed text-ink-secondary">
          <span className="font-semibold text-warning">Watch out: </span>
          {model.watch_out}
        </p>
      )}

      {model.recommended_for.length > 0 && (
        <div className="mt-auto flex flex-wrap gap-1 pt-3">
          {model.recommended_for.map((use) => (
            <Badge key={use} tone="neutral">
              {use}
            </Badge>
          ))}
        </div>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------

function Estimator({ selection, pricingAsOf }: { selection: ModelDefaults; pricingAsOf: string }) {
  const [contacts, setContacts] = useState(1000);
  const [exchanges, setExchanges] = useState(8);
  const [connectRate, setConnectRate] = useState(55);

  const params = useMemo(
    () => ({
      ...selection,
      contacts: Math.max(1, contacts || 1),
      exchanges: Math.max(1, exchanges || 1),
      connect_rate: connectRate / 100,
    }),
    [selection, contacts, exchanges, connectRate],
  );

  // Re-estimate as the inputs change, debounced, keeping the last figure on
  // screen meanwhile — dragging a slider shouldn't strobe a skeleton.
  const estimate = useAsync(() => api.estimate(params), []);
  const key = JSON.stringify(params);
  const firstRun = useRef(true);
  const { reload } = estimate;
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    const timer = window.setTimeout(reload, 250);
    return () => window.clearTimeout(timer);
  }, [key, reload]);
  const data = estimate.data;

  return (
    <Card>
      <CardHeader
        title="What this will cost"
        subtitle={`Model spend only — telephony is billed by your carrier. Prices as of ${pricingAsOf}.`}
        icon={<IconCoin size={16} />}
      />
      <div className="grid gap-6 p-5 lg:grid-cols-[300px_1fr]">
        <div className="space-y-4">
          <Field label="Contacts in the campaign">
            <Input type="number" min={1} value={contacts} onChange={(e) => setContacts(Number(e.target.value))} className="tnum" />
          </Field>
          <Field label={`Exchanges per call — ${exchanges}`} hint="One exchange is the agent speaking and the person replying.">
            <input type="range" min={2} max={24} value={exchanges} onChange={(e) => setExchanges(Number(e.target.value))} className="w-full" />
          </Field>
          <Field label={`Expected connect rate — ${connectRate}%`} hint="Dials that reach a person.">
            <input type="range" min={5} max={100} value={connectRate} onChange={(e) => setConnectRate(Number(e.target.value))} className="w-full" />
          </Field>
        </div>

        <div aria-live="polite">
          {estimate.error ? (
            <ErrorNote message={estimate.error} onRetry={estimate.reload} />
          ) : !data ? (
            <Skeleton className="h-44 w-full rounded-xl" />
          ) : (
            <>
              <div className="relative overflow-hidden rounded-xl bg-brand p-5 text-on-brand">
                <div aria-hidden className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/10" />
                <p className="text-sm font-medium opacity-80">Projected model spend</p>
                <p className={cx("tnum mt-2 text-4xl font-semibold leading-none tracking-tight transition-opacity", estimate.refreshing && "opacity-70")}>
                  {formatUsd(data.total_cost_usd)}
                </p>
                <p className="mt-2 text-xs opacity-75">
                  {data.connected_calls.toLocaleString()} connected calls out of {data.contacts.toLocaleString()} contacts
                </p>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <MiniFigure label="Per connected call" value={formatUsd(data.cost_per_call_usd, 4)} icon={<IconUsers size={15} />} />
                <MiniFigure label="On the call" value={formatUsd(data.conversation_cost_usd, 4)} icon={<IconBolt size={15} />} />
                <MiniFigure label="After the call" value={formatUsd(data.extraction_cost_usd, 4)} icon={<IconClock size={15} />} />
              </div>
              <p className="mt-3 text-xs leading-relaxed text-ink-muted">
                Assumes the persona prompt is served from cache. Real calls record actual token counts; this is a projection,
                not a quote.
              </p>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

function MiniFigure({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className="rounded-lg border border-line px-3 py-2.5">
      <div className="flex items-center justify-between">
        <p className="text-2xs font-medium text-ink-muted">{label}</p>
        <span className="text-ink-muted/70">{icon}</span>
      </div>
      <p className="tnum mt-1 text-lg font-semibold leading-none text-ink">{value}</p>
    </div>
  );
}
