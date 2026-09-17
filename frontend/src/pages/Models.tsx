/**
 * Model selection.
 */

import { useMemo, useState } from "react";
import {
  api,
  type EffortOption,
  type ModelDefaults,
  type ModelRole,
  type ModelSpec,
} from "../api";
import {
  IconBolt,
  IconCheck,
  IconChip,
  IconClock,
  IconCoin,
  IconUsers,
} from "../components/icons";
import {
  Button,
  Card,
  CardHeader,
  ErrorNote,
  Field,
  PageWrapper,
  Skeleton,
  inputClass,
} from "../components/ui";
import { useAsync } from "../hooks";

const SPEED_LABEL: Record<ModelSpec["speed"], string> = {
  fastest: "Fastest",
  fast: "Fast",
  balanced: "Balanced",
  deliberate: "Deliberate",
};

const SPEED_SWATCH: Record<ModelSpec["speed"], string> = {
  fastest: "bg-ramp-1",
  fast: "bg-ramp-2",
  balanced: "bg-ramp-4",
  deliberate: "bg-ramp-5",
};

const ROLE_COPY: Record<
  ModelRole,
  { title: string; subtitle: string; icon: React.ReactNode }
> = {
  conversation: {
    title: "On the call",
    subtitle:
      "Runs live while someone is on the line. Latency is the whole game — every 100ms is heard.",
    icon: <IconBolt size={16} />,
  },
  extraction: {
    title: "After the call",
    subtitle:
      "Reads the transcript and writes the record. Latency is free here; being wrong is not.",
    icon: <IconCheck size={16} />,
  },
};

export default function Models() {
  const catalog = useAsync(() => api.models(), []);
  const [draft, setDraft] = useState<ModelDefaults | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const current: ModelDefaults | null = draft ?? catalog.data?.defaults ?? null;
  const dirty =
    !!draft &&
    !!catalog.data &&
    JSON.stringify(draft) !== JSON.stringify(catalog.data.defaults);

  const update = (patch: Partial<ModelDefaults>) => {
    if (!current) return;
    setSaved(false);
    setDraft({ ...current, ...patch });
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      await api.saveModelDefaults(draft);
      setSaved(true);
      catalog.reload();
      setDraft(null);
    } catch (err) {
      setSaveError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageWrapper className="mx-auto max-w-[1180px] px-3 py-4 sm:px-6 sm:py-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Models</h1>
          <p className="mt-0.5 max-w-2xl text-sm text-ink-muted">
            A call bills two models with opposite priorities. Assign each one
            separately — new campaigns inherit these.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saved && !dirty && (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-good">
              <IconCheck size={13} /> Defaults saved
            </span>
          )}
          <Button onClick={save} disabled={!dirty || saving}>
            {saving ? "Saving\u2026" : "Save as default"}
          </Button>
        </div>
      </header>

      {saveError && <div className="mb-4"><ErrorNote message={saveError} /></div>}
      {catalog.error && <div className="mb-4"><ErrorNote message={catalog.error} /></div>}

      {catalog.loading || !catalog.data || !current ? (
        <div className="space-y-3">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      ) : (
        <div className="space-y-7">
          {catalog.data.roles.map((role) => (
            <RoleSection
              key={role}
              role={role}
              models={catalog.data!.models.filter((m) => m.roles.includes(role))}
              efforts={catalog.data!.efforts}
              selectedModel={
                role === "conversation"
                  ? current.conversation_model
                  : current.extraction_model
              }
              selectedEffort={
                role === "conversation"
                  ? current.conversation_effort
                  : current.extraction_effort
              }
              onModel={(id) =>
                update(
                  role === "conversation"
                    ? { conversation_model: id }
                    : { extraction_model: id },
                )
              }
              onEffort={(value) =>
                update(
                  role === "conversation"
                    ? { conversation_effort: value }
                    : { extraction_effort: value },
                )
              }
            />
          ))}

          <Estimator selection={current} pricingAsOf={catalog.data.pricing_as_of} />
        </div>
      )}
    </PageWrapper>
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
    <section>
      <div className="mb-3 flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand/12 text-brand">
          {copy.icon}
        </span>
        <div>
          <h2 className="text-sm font-bold tracking-tight">{copy.title}</h2>
          <p className="mt-0.5 text-xs text-ink-muted">{copy.subtitle}</p>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {models.map((model) => (
          <ModelCard
            key={model.id}
            model={model}
            selected={model.id === selectedModel}
            onSelect={() => onModel(model.id)}
          />
        ))}
      </div>

      <div className="card-static mt-3 rounded-lg px-4 py-3">
        <p className="text-[11px] font-medium text-ink-muted">Thinking effort</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {efforts.map((effort) => {
            const active = effort.value === selectedEffort;
            return (
              <button
                key={effort.value}
                type="button"
                onClick={() => onEffort(effort.value)}
                title={effort.description}
                className={`ripple rounded-lg border px-3 py-2 text-left text-xs transition-colors duration-150 ${
                  active
                    ? "border-brand/40 bg-brand/12 text-ink"
                    : "border-white/10 text-ink-secondary hover:border-brand/20 hover:text-ink"
                }`}
              >
                <span className="font-semibold">{effort.label}</span>
                <span className="tnum ml-1.5 text-ink-muted">
                  ×{effort.output_multiplier.toFixed(1)} output
                </span>
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          {efforts.find((e) => e.value === selectedEffort)?.description}
        </p>
      </div>
    </section>
  );
}

function ModelCard({
  model,
  selected,
  onSelect,
}: {
  model: ModelSpec;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`ripple flex h-full flex-col rounded-lg border p-4 text-left transition-all duration-150 ${
        selected
          ? "border-brand/40 bg-brand/8 elevation-2"
          : "card"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={selected ? "text-brand" : "text-ink-muted"}>
            <IconChip size={16} />
          </span>
          <span className="text-sm font-bold tracking-tight">{model.name}</span>
        </div>
        {selected && (
          <span className="flex items-center gap-1 rounded-md bg-brand px-2 py-0.5 text-[11px] font-bold text-plane">
            <IconCheck size={11} /> In use
          </span>
        )}
      </div>

      <p className="mt-2 text-xs leading-relaxed text-ink-secondary">{model.tagline}</p>

      <div className="mt-2.5 flex items-center gap-1.5 text-xs text-ink-muted">
        <span className={`inline-block h-2 w-2 rounded-full ${SPEED_SWATCH[model.speed]}`} />
        <span>{SPEED_LABEL[model.speed]}</span>
        <span>·</span>
        <span className="tnum">{(model.context_tokens / 1000).toLocaleString()}K context</span>
      </div>

      <dl className="mt-2.5 grid grid-cols-3 gap-2 rounded-lg bg-elevated px-3 py-2 text-xs">
        {[
          ["Input", model.input_per_mtok],
          ["Output", model.output_per_mtok],
          ["Cached", model.cache_read_per_mtok],
        ].map(([label, value]) => (
          <div key={label as string}>
            <dt className="text-[11px] font-medium text-ink-muted">{label}</dt>
            <dd className="tnum font-bold">${(value as number).toFixed(2)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-1 text-[10px] text-ink-muted">per million tokens</p>

      <ul className="mt-2.5 space-y-1">
        {model.strengths.slice(0, 3).map((s) => (
          <li key={s} className="flex gap-1.5 text-xs leading-relaxed text-ink-secondary">
            <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-brand" />
            {s}
          </li>
        ))}
      </ul>

      {model.watch_out && (
        <p className="mt-2.5 rounded-lg border border-warning/20 bg-warning/5 px-3 py-2 text-[11px] leading-relaxed text-ink-secondary">
          <span className="font-bold text-warning">Watch out: </span>
          {model.watch_out}
        </p>
      )}

      {model.recommended_for.length > 0 && (
        <div className="mt-auto flex flex-wrap gap-1 pt-2.5">
          {model.recommended_for.map((use) => (
            <span key={use} className="rounded-md bg-elevated px-2 py-0.5 text-[11px] text-ink-muted">
              {use}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------

function Estimator({
  selection,
  pricingAsOf,
}: {
  selection: ModelDefaults;
  pricingAsOf: string;
}) {
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

  const estimate = useAsync(() => api.estimate(params), [JSON.stringify(params)]);
  const data = estimate.data;

  return (
    <Card hover={false}>
      <CardHeader
        title="What this will cost"
        subtitle={`Model spend only — telephony is billed by your carrier. Prices as of ${pricingAsOf}.`}
        action={<span className="text-ink-muted"><IconCoin size={18} /></span>}
      />

      <div className="grid gap-5 p-5 lg:grid-cols-[320px_1fr]">
        <div className="space-y-3">
          <Field label="Contacts in the campaign">
            <input
              type="number"
              min={1}
              value={contacts}
              onChange={(e) => setContacts(Number(e.target.value))}
              className={`${inputClass} tnum`}
            />
          </Field>

          <Field
            label={`Exchanges per call \u2014 ${exchanges}`}
            hint="One exchange is the agent speaking and the person replying."
          >
            <input
              type="range"
              min={2}
              max={24}
              value={exchanges}
              onChange={(e) => setExchanges(Number(e.target.value))}
              className="mt-2 w-full accent-[var(--color-brand)]"
            />
          </Field>

          <Field
            label={`Expected connect rate \u2014 ${connectRate}%`}
            hint="Dials that reach a person."
          >
            <input
              type="range"
              min={5}
              max={100}
              value={connectRate}
              onChange={(e) => setConnectRate(Number(e.target.value))}
              className="mt-2 w-full accent-[var(--color-brand)]"
            />
          </Field>
        </div>

        <div>
          {estimate.error ? (
            <ErrorNote message={estimate.error} />
          ) : !data ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <>
              <div className="rounded-lg bg-brand p-5 text-plane">
                <p className="text-sm font-medium opacity-75">Projected model spend</p>
                <p className="tnum mt-2 text-4xl font-bold leading-none tracking-tight">
                  ${data.total_cost_usd.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </p>
                <p className="mt-2 text-xs opacity-60">
                  {data.connected_calls.toLocaleString()} connected calls out of{" "}
                  {data.contacts.toLocaleString()} contacts
                </p>
              </div>

              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <MiniFigure
                  label="Per connected call"
                  value={`$${data.cost_per_call_usd.toFixed(4)}`}
                  icon={<IconUsers size={15} />}
                />
                <MiniFigure
                  label="On the call"
                  value={`$${data.conversation_cost_usd.toFixed(4)}`}
                  icon={<IconBolt size={15} />}
                />
                <MiniFigure
                  label="After the call"
                  value={`$${data.extraction_cost_usd.toFixed(4)}`}
                  icon={<IconClock size={15} />}
                />
              </div>

              <p className="mt-2 text-xs leading-relaxed text-ink-muted">
                Assumes the persona prompt is served from cache. Real calls
                record actual token counts; this is a projection, not a quote.
              </p>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

function MiniFigure({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="card-static rounded-lg px-3 py-2.5">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium text-ink-muted">{label}</p>
        <span className="text-ink-muted/60">{icon}</span>
      </div>
      <p className="tnum mt-1 text-lg font-bold leading-none">{value}</p>
    </div>
  );
}
