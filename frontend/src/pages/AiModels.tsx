/**
 * AI models (replaces "Models"): the workspace's model providers, which of
 * them runs on the call and after it, every model they offer with its price,
 * and a calculator for what a campaign will cost end to end.
 *
 *   ?add=1   opens the Add provider drawer (from checklists and blockers)
 */

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  api,
  type LanguageOption,
  type ModelCatalog,
  type Provider,
  type ProviderModel,
  type WorkspaceModelDefaults,
  isMissing,
  unlessMissing,
} from "../api";
import { useCanAdmin } from "../auth";
import { IconAlert, IconBolt, IconCheck, IconChip, IconCoin, IconPencil, IconPlus, IconRefresh, IconSearch, IconTrash } from "../components/icons";
import { CostBreakdown, useEstimate, estimateOf } from "../components/models/estimate";
import { ProviderMark, STATUS_META, bestFor, isEnvRow, money, perMillion, speedLabel } from "../components/models/meta";
import { ModelPicker, invalidateModels, modelsOf } from "../components/models/ModelPicker";
import { ProviderDrawer } from "../components/models/ProviderDrawer";
import { useProviders } from "../components/models/useProviders";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  NotAvailable,
  Page,
  PageHeader,
  SectionHeader,
  Segmented,
  Select,
  Skeleton,
  Switch,
  cx,
  toast,
} from "../components/ui";
import { formatMs } from "../format";
import { useAsync, useDocumentTitle } from "../hooks";
import { useHealth } from "../data";

export default function AiModels() {
  useDocumentTitle("AI models");
  const canAdmin = useCanAdmin();
  const { health } = useHealth();
  const [params, setParams] = useSearchParams();
  const { providers, presets, error, unavailable, loading, reload, upsert, remove } = useProviders();
  const [drawer, setDrawer] = useState<{ editing: Provider | null; kind: string | null } | null>(null);
  const [modelsVersion, setModelsVersion] = useState(0);

  // ?add=1 (or ?add=<preset>) opens the drawer once, then drops the param.
  useEffect(() => {
    if (!params.has("add")) return;
    const kind = params.get("add");
    setDrawer({ editing: null, kind: kind && kind !== "1" ? kind : null });
    const next = new URLSearchParams(params);
    next.delete("add");
    setParams(next, { replace: true });
  }, [params, setParams]);

  const saved = (p: Provider) => {
    upsert(p);
    invalidateModels(p.id);
    setModelsVersion((v) => v + 1);
  };

  return (
    <Page width="wide">
      <PageHeader
        icon={<IconChip size={18} />}
        title="AI models"
        description="Bring any LLM. Connect providers, choose what runs on the call and after it, and see what a campaign costs before it dials."
        actions={
          !unavailable &&
          canAdmin && (
            <Button icon={<IconPlus size={14} />} onClick={() => setDrawer({ editing: null, kind: null })}>
              Add provider
            </Button>
          )
        }
      />

      {unavailable ? (
        <LegacyModels providerLabel={health?.provider_label ?? ""} />
      ) : (
        <div className="space-y-10">
          <section aria-labelledby="providers-heading">
            <SectionHeader
              title={<span id="providers-heading">Providers</span>}
              description="Keys are encrypted and never shown again. Providers set by environment variables appear read-only; adding one here takes precedence."
            />
            {error ? (
              <ErrorNote message={error} onRetry={reload} />
            ) : loading || !providers ? (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-40 rounded-xl" />
                ))}
              </div>
            ) : providers.length === 0 ? (
              <Card>
                <EmptyState
                  avatar="thinking"
                  title="No model provider yet"
                  hint="Nothing can talk until one is connected. Add a key for OpenAI, Anthropic, Gemini, Sarvam, Groq or any OpenAI-compatible endpoint."
                  action={
                    canAdmin && (
                      <Button icon={<IconPlus size={14} />} onClick={() => setDrawer({ editing: null, kind: null })}>
                        Add provider
                      </Button>
                    )
                  }
                />
              </Card>
            ) : (
              <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {providers.map((p) => (
                  <li key={p.id}>
                    <ProviderCard
                      provider={p}
                      canAdmin={canAdmin}
                      onChanged={saved}
                      onRemoved={remove}
                      onEdit={() => (isEnvRow(p) ? setDrawer({ editing: null, kind: p.kind }) : setDrawer({ editing: p, kind: null }))}
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>

          {providers && providers.length > 0 && (
            <>
              <DefaultsSection providers={providers} canAdmin={canAdmin} />
              <ModelBrowser providers={providers} version={modelsVersion} />
              <CostCalculator providers={providers} />
            </>
          )}
        </div>
      )}

      <ProviderDrawer
        open={drawer !== null}
        onClose={() => setDrawer(null)}
        presets={presets}
        editing={drawer?.editing ?? null}
        initialKind={drawer?.kind ?? null}
        onSaved={saved}
        onRemoved={remove}
      />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Provider card
// ---------------------------------------------------------------------------

function ProviderCard({
  provider: p,
  canAdmin,
  onChanged,
  onRemoved,
  onEdit,
}: {
  provider: Provider;
  canAdmin: boolean;
  onChanged: (p: Provider) => void;
  onRemoved: (id: string) => void;
  onEdit: () => void;
}) {
  const [testing, setTesting] = useState(false);
  const [lastTest, setLastTest] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);
  const [confirm, setConfirm] = useState<"delete" | "disable" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const env = isEnvRow(p);
  const status = STATUS_META[p.status] ?? STATUS_META.untested;

  const test = async () => {
    setTesting(true);
    try {
      const result = await api.testProvider(p.id);
      onChanged({ ...p, status: result.ok ? "ok" : "error", last_error: result.ok ? null : (result.error ?? "Test failed") });
      setLastTest(result.ok ? `Answered in ${result.latency_ms != null ? formatMs(result.latency_ms) : "time"}${result.model ? ` by ${result.model}` : ""}` : null);
      if (result.ok) toast.success(`${p.label} is working`);
      else toast.error(`${p.label} failed the test`, result.error ?? undefined);
    } catch (err) {
      toast.error(`Couldn't test ${p.label}`, (err as Error).message);
    } finally {
      setTesting(false);
    }
  };

  const setEnabled = async (enabled: boolean) => {
    setToggling(true);
    try {
      onChanged(await api.updateProvider(p.id, { enabled }));
      toast.success(enabled ? `${p.label} enabled` : `${p.label} disabled`, enabled ? undefined : "Campaigns using it fall back to the workspace default.");
    } catch (err) {
      toast.error(`Couldn't ${enabled ? "enable" : "disable"} ${p.label}`, (err as Error).message);
    } finally {
      setToggling(false);
      setConfirm(null);
    }
  };

  const destroy = async () => {
    setDeleting(true);
    try {
      await api.deleteProvider(p.id);
      onRemoved(p.id);
      toast.success(`${p.label} removed`, "Campaigns that used it now use the workspace default.");
      setConfirm(null);
    } catch (err) {
      const status = (err as { status?: number }).status;
      toast.error(
        `Couldn't remove ${p.label}`,
        status === 409 ? "It's a workspace default. Pick another default below first." : (err as Error).message,
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Card className={cx("flex h-full flex-col", !p.enabled && "opacity-75")}>
      <div className="flex items-start gap-3 px-4 pt-4">
        <ProviderMark kind={p.kind} label={p.label} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="truncate text-sm font-semibold text-ink">{p.label}</h3>
            <span className="flex shrink-0 items-center gap-1.5 text-xs text-ink-secondary">
              <span className={cx("h-2 w-2 rounded-full", p.enabled ? status.dot : "bg-ink-muted/40")} aria-hidden />
              {p.enabled ? status.label : "Disabled"}
            </span>
          </div>
          <p className="mt-0.5 truncate text-xs text-ink-muted">
            {p.key_hint ? (
              <span className="font-mono">•••• {p.key_hint}</span>
            ) : (
              "No key"
            )}
            {p.base_url && <span title={p.base_url}> · {hostOf(p.base_url)}</span>}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 px-4">
        <Badge tone={p.supports_tools ? "good" : "neutral"} icon={p.supports_tools ? <IconCheck size={10} /> : undefined}>
          {p.supports_tools ? "Tools" : "No tools"}
        </Badge>
        <Badge tone="neutral">
          {p.models_count} {p.models_count === 1 ? "model" : "models"}
        </Badge>
        {env && <Badge tone="info">From environment</Badge>}
      </div>
      {p.enabled && p.status === "error" && p.last_error && (
        <p className="mx-4 mt-3 line-clamp-2 flex items-start gap-1.5 text-xs text-critical" title={p.last_error}>
          <IconAlert size={12} className="mt-0.5 shrink-0" /> {p.last_error}
        </p>
      )}
      {lastTest && p.status === "ok" && <p className="mx-4 mt-3 text-xs text-good">{lastTest}</p>}
      <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t border-line px-3 py-2.5 pt-2.5">
        <Button size="sm" variant="secondary" icon={<IconBolt size={13} />} onClick={test} loading={testing} disabled={!p.enabled}>
          Test
        </Button>
        {canAdmin && (
          <Button size="sm" variant="ghost" icon={env ? <IconPlus size={13} /> : <IconPencil size={13} />} onClick={onEdit}>
            {env ? "Use an app key" : "Edit"}
          </Button>
        )}
        {canAdmin && !env && (
          <div className="ml-auto flex items-center gap-1">
            <Button size="sm" variant="ghost" loading={toggling} onClick={() => (p.enabled ? setConfirm("disable") : void setEnabled(true))}>
              {p.enabled ? "Disable" : "Enable"}
            </Button>
            <Button size="sm" variant="ghost" icon={<IconTrash size={13} />} aria-label={`Remove ${p.label}`} onClick={() => setConfirm("delete")} />
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirm === "delete"}
        onClose={() => setConfirm(null)}
        onConfirm={destroy}
        busy={deleting}
        title={`Remove ${p.label}?`}
        description="Its key is deleted. Campaigns that use it switch to the workspace default on their next call."
        confirmLabel="Remove provider"
      />
      <ConfirmDialog
        open={confirm === "disable"}
        onClose={() => setConfirm(null)}
        onConfirm={() => void setEnabled(false)}
        busy={toggling}
        title={`Disable ${p.label}?`}
        description="The key is kept. Campaigns that use it fall back to the workspace default until you enable it again."
        confirmLabel="Disable"
      />
    </Card>
  );
}

const hostOf = (url: string) => {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
};

// ---------------------------------------------------------------------------
// Workspace defaults
// ---------------------------------------------------------------------------

const EMPTY_DEFAULTS: WorkspaceModelDefaults = {
  conversation: { provider_id: null, model: null },
  extraction: { provider_id: null, model: null },
};

function DefaultsSection({ providers, canAdmin }: { providers: Provider[]; canAdmin: boolean }) {
  const saved = useAsync(() => unlessMissing(api.workspaceModelDefaults()), []);
  const [draft, setDraft] = useState<WorkspaceModelDefaults | null>(null);
  const [saving, setSaving] = useState(false);
  const current = draft ?? saved.data ?? EMPTY_DEFAULTS;
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(saved.data ?? EMPTY_DEFAULTS);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      saved.setData(await api.saveWorkspaceModelDefaults(draft));
      setDraft(null);
      toast.success("Defaults saved", "Campaigns without their own pick use these from the next call.");
    } catch (err) {
      toast.error("Couldn't save the defaults", (err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const ROLES = [
    { key: "conversation" as const, title: "On the call", hint: "Runs live while someone is on the line. Every 100 ms of latency is heard." },
    { key: "extraction" as const, title: "After the call", hint: "Reads the transcript and writes the record. Accuracy matters more than speed." },
  ];

  return (
    <section aria-labelledby="defaults-heading">
      <SectionHeader
        title={<span id="defaults-heading">Workspace defaults</span>}
        description="What campaigns use unless they pick their own. Leaving a model blank uses the provider's recommended one."
        action={
          dirty && (
            <>
              <Button variant="ghost" onClick={() => setDraft(null)} disabled={saving}>
                Discard
              </Button>
              <Button onClick={save} loading={saving}>
                Save defaults
              </Button>
            </>
          )
        }
      />
      {saved.loading ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : saved.error ? (
        <ErrorNote message={saved.error} onRetry={saved.reload} />
      ) : saved.data === null ? (
        <NotAvailable>Workspace defaults arrive with the next server update. Until then calls use the first configured provider.</NotAvailable>
      ) : (
        <Card>
          <div className="divide-y divide-line">
            {ROLES.map((role) => (
              <div key={role.key} className="grid gap-4 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] lg:items-center">
                <div>
                  <p className="text-sm font-semibold text-ink">{role.title}</p>
                  <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{role.hint}</p>
                </div>
                <ModelPicker
                  providers={providers}
                  providerId={current[role.key].provider_id}
                  model={current[role.key].model}
                  role={role.key}
                  disabled={!canAdmin}
                  onChange={(next) => setDraft({ ...current, [role.key]: next })}
                />
              </div>
            ))}
          </div>
          {!canAdmin && <p className="border-t border-line px-5 py-2.5 text-xs text-ink-muted">Only owners and admins can change the defaults.</p>}
        </Card>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Model browser
// ---------------------------------------------------------------------------

interface Row extends ProviderModel {
  provider: Provider;
}

function ModelBrowser({ providers, version }: { providers: Provider[]; version: number }) {
  const enabled = providers.filter((p) => p.enabled);
  const ids = enabled.map((p) => p.id).join(",");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [failed, setFailed] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [providerId, setProviderId] = useState("");
  const [role, setRole] = useState<"all" | "conversation" | "extraction">("all");
  const [toolsOnly, setToolsOnly] = useState(false);
  const [sort, setSort] = useState<"price" | "name">("price");

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    Promise.allSettled(enabled.map((p) => modelsOf(p.id).then((list) => list.map((m) => ({ ...m, provider: p }))))).then((results) => {
      if (cancelled) return;
      setRows(results.flatMap((r) => (r.status === "fulfilled" ? r.value : [])));
      setFailed(enabled.filter((_, i) => results[i].status === "rejected").map((p) => p.label));
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids, version]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (rows ?? []).filter(
      (m) =>
        (!providerId || m.provider.id === providerId) &&
        (role === "all" || m.roles.length === 0 || m.roles.includes(role)) &&
        (!toolsOnly || m.supports_tools) &&
        (!q || `${m.name} ${m.id} ${m.provider.label}`.toLowerCase().includes(q)),
    );
    const cost = (m: Row) => (m.input_per_mtok === null || m.output_per_mtok === null ? Infinity : m.input_per_mtok + m.output_per_mtok * 3);
    return list.sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name) : cost(a) - cost(b)));
  }, [rows, query, providerId, role, toolsOnly, sort]);

  return (
    <section aria-labelledby="browser-heading">
      <SectionHeader
        title={<span id="browser-heading">Model browser</span>}
        description="Every model your connected providers offer. Prices are USD per 1M tokens, input and output."
      />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <label className="relative min-w-0 flex-1 basis-48">
            <span className="sr-only">Search models</span>
            <IconSearch size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search models" className="pl-9" />
          </label>
          <Select value={providerId} onChange={(e) => setProviderId(e.target.value)} aria-label="Provider" className="w-full sm:w-44">
            <option value="">All providers</option>
            {enabled.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </Select>
          <Segmented
            label="Role"
            size="sm"
            value={role}
            onChange={setRole}
            options={[
              { value: "all", label: "All" },
              { value: "conversation", label: "On the call" },
              { value: "extraction", label: "After" },
            ]}
          />
          <Segmented
            label="Sort"
            size="sm"
            value={sort}
            onChange={setSort}
            options={[
              { value: "price", label: "Cheapest" },
              { value: "name", label: "Name" },
            ]}
          />
          <Switch checked={toolsOnly} onChange={setToolsOnly} label="Tools only" className="items-center gap-2" />
        </div>
        {failed.length > 0 && (
          <p className="border-b border-line bg-warning/6 px-4 py-2 text-xs text-ink-secondary">
            Couldn't list models for {failed.join(", ")}. Test the provider above.
          </p>
        )}
        <div className="max-h-[32rem] overflow-auto">
          {rows === null ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : visible.length === 0 ? (
            <EmptyState compact avatar="thinking" title="No models match" hint="Clear the search or filters." />
          ) : (
            <table className="data-table min-w-[720px]">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr>
                  <th>Model</th>
                  <th>Provider</th>
                  <th className="text-right">In / 1M</th>
                  <th className="text-right">Out / 1M</th>
                  <th>Speed</th>
                  <th>Tools</th>
                  <th>Best for</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((m) => (
                  <tr key={`${m.provider.id}:${m.id}`}>
                    <td>
                      <span className="block font-medium text-ink">{m.name}</span>
                      <code className="block font-mono text-2xs text-ink-muted">{m.id}</code>
                    </td>
                    <td className="whitespace-nowrap">
                      <span className="flex items-center gap-2 text-ink-secondary">
                        <ProviderMark kind={m.provider.kind} label={m.provider.label} size="sm" />
                        {m.provider.label}
                      </span>
                    </td>
                    <Price value={m.input_per_mtok} />
                    <Price value={m.output_per_mtok} />
                    <td className="whitespace-nowrap text-xs text-ink-secondary">{speedLabel(m.speed)}</td>
                    <td className="text-xs">{m.supports_tools ? <span className="inline-flex items-center gap-1 text-good"><IconCheck size={12} /> Yes</span> : <span className="text-ink-muted">No</span>}</td>
                    <td className="whitespace-nowrap">
                      <Badge tone="neutral">{bestFor(m)}</Badge>
                      {m.source !== "catalog" && <Badge tone="info" className="ml-1.5 capitalize">{m.source}</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </section>
  );
}

function Price({ value }: { value: number | null }) {
  return (
    <td className={cx("tnum whitespace-nowrap text-right", value === null ? "text-xs text-ink-muted" : "text-ink")}>{perMillion(value)}</td>
  );
}

// ---------------------------------------------------------------------------
// Cost calculator
// ---------------------------------------------------------------------------

function CostCalculator({ providers }: { providers: Provider[] }) {
  const enabled = providers.filter((p) => p.enabled);
  const languages = useAsync(() => api.languages(), []);
  const [providerId, setProviderId] = useState<string | null>(enabled[0]?.id ?? null);
  const [model, setModel] = useState<string | null>(null);
  const [language, setLanguage] = useState("hi");
  const [minutes, setMinutes] = useState("3");
  const [calls, setCalls] = useState("1000");
  const [region, setRegion] = useState<"IN" | "US">("IN");
  const [voice, setVoice] = useState(true);

  const callsN = Math.max(1, Math.round(Number(calls) || 0));
  const minutesN = Math.max(0.5, Number(minutes) || 0);
  const state = useEstimate({
    provider_id: providerId,
    conversation_model: model,
    language,
    minutes_per_call: minutesN,
    calls: callsN,
    telephony_region: region,
    include_voice: voice,
  });
  const estimate = estimateOf(state);

  return (
    <section aria-labelledby="calc-heading">
      <SectionHeader
        title={<span id="calc-heading">Cost calculator</span>}
        description="Everything a call costs, not just the model: speech-to-text, the voice and carrier minutes too."
      />
      <Card>
        <div className="grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="space-y-4 border-b border-line px-5 py-5 lg:border-b-0 lg:border-r">
            <ModelPicker
              providers={enabled}
              providerId={providerId}
              model={model}
              role="conversation"
              onChange={(next) => {
                setProviderId(next.provider_id);
                setModel(next.model);
              }}
            />
            <Field label="Language">
              <Select value={language} onChange={(e) => setLanguage(e.target.value)}>
                {(languages.data ?? [{ code: "hi", name: "Hindi", native_name: "हिन्दी" }, { code: "en", name: "English", native_name: "English" }]).map(
                  (l: LanguageOption) => (
                    <option key={l.code} value={l.code}>
                      {l.name}
                    </option>
                  ),
                )}
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Minutes per call">
                <Input type="number" min={0.5} step={0.5} value={minutes} onChange={(e) => setMinutes(e.target.value)} className="tnum" />
              </Field>
              <Field label="Number of calls">
                <Input type="number" min={1} step={100} value={calls} onChange={(e) => setCalls(e.target.value)} className="tnum" />
              </Field>
            </div>
            <Field label="Calling region" group>
              <Segmented
                label="Calling region"
                value={region}
                onChange={setRegion}
                options={[
                  { value: "IN", label: "India" },
                  { value: "US", label: "United States" },
                ]}
              />
            </Field>
            <Switch checked={voice} onChange={setVoice} label="Include voice" description="Speech-to-text, text-to-speech and telephony. Off shows the models alone." />
          </div>

          <div className="px-5 py-5" aria-live="polite">
            {state.status === "unavailable" ? (
              <NotAvailable>The full-call estimator arrives with the next server update.</NotAvailable>
            ) : state.status === "error" ? (
              <Callout tone="critical" title="Couldn't estimate">
                {state.message}
              </Callout>
            ) : !estimate ? (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-16" />
                  ))}
                </div>
                <Skeleton className="h-3 rounded-full" />
                <Skeleton className="h-24" />
              </div>
            ) : (
              <div className={cx("transition-opacity duration-200", state.status === "loading" && "opacity-60")}>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <Headline label="Per call" value={money(estimate.per_call.total)} />
                  <Headline label="Per minute" value={money(estimate.per_minute_total)} />
                  <Headline label={`For ${estimate.for_calls.calls.toLocaleString()} calls`} value={money(estimate.for_calls.total)} strong />
                </div>
                {estimate.unknown.length > 0 && (
                  <Callout tone="warning" className="mt-4" title="Some prices aren't set">
                    Not counted: {estimate.unknown.join(", ")}. Totals are a floor, not the full cost.
                  </Callout>
                )}
                <div className="mt-5">
                  <p className="mb-2 text-xs font-medium text-ink-secondary">Per call, then for {estimate.for_calls.calls.toLocaleString()} calls</p>
                  <CostBreakdown estimate={estimate} calls={estimate.for_calls.calls} />
                </div>
                {estimate.assumptions.length > 0 && (
                  <div className="mt-5 rounded-lg bg-subtle/60 px-4 py-3">
                    <p className="text-xs font-medium text-ink-secondary">Assumptions</p>
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs leading-relaxed text-ink-muted">
                      {estimate.assumptions.map((a) => (
                        <li key={a}>{a}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="mt-3 text-2xs text-ink-muted">Prices as of {estimate.pricing_as_of}. Carrier and speech prices vary by contract.</p>
              </div>
            )}
          </div>
        </div>
      </Card>
    </section>
  );
}

function Headline({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={cx("tnum mt-1 text-2xl font-semibold leading-none tracking-tight", strong ? "text-brand" : "text-ink")}>{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Older backend: no /api/providers yet
// ---------------------------------------------------------------------------

function LegacyModels({ providerLabel }: { providerLabel: string }) {
  const catalog = useAsync(async () => {
    try {
      return await api.models();
    } catch (err) {
      if (isMissing(err)) return null;
      throw err;
    }
  }, []);
  const data: ModelCatalog | null = catalog.data;

  return (
    <div className="space-y-6">
      <NotAvailable title="Adding providers in the app needs a server update">
        This server picks one provider from its environment variables{providerLabel ? ` (currently ${providerLabel})` : ""}. The models it
        offers are listed below.
      </NotAvailable>
      {catalog.loading ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : catalog.error ? (
        <ErrorNote message={catalog.error} onRetry={catalog.reload} />
      ) : data ? (
        <Card className="overflow-hidden">
          <CardHeader title={`${data.provider_label || "Available"} models`} subtitle={`Prices per 1M tokens, as of ${data.pricing_as_of}.`} icon={<IconCoin size={15} />} action={<Button size="sm" variant="ghost" icon={<IconRefresh size={13} />} onClick={catalog.reload}>Refresh</Button>} />
          <div className="overflow-x-auto">
            <table className="data-table min-w-[560px]">
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="text-right">In / 1M</th>
                  <th className="text-right">Out / 1M</th>
                  <th>Speed</th>
                  <th>Used for</th>
                </tr>
              </thead>
              <tbody>
                {data.models.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <span className="block font-medium text-ink">{m.name}</span>
                      <span className="block text-2xs text-ink-muted">{m.tagline}</span>
                    </td>
                    <Price value={m.input_per_mtok} />
                    <Price value={m.output_per_mtok} />
                    <td className="text-xs text-ink-secondary">{speedLabel(m.speed)}</td>
                    <td className="text-xs text-ink-secondary">
                      {m.roles.map((r) => (r === "conversation" ? "On the call" : "After the call")).join(", ")}
                      {(data.defaults.conversation_model === m.id || data.defaults.extraction_model === m.id) && (
                        <Badge tone="brand" className="ml-1.5">
                          Default
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
