/**
 * Add or edit a model provider: pick a preset (letter marks, never brand
 * artwork), paste a key, add a base URL when the preset needs one, list any
 * custom models with their prices, and test before saving.
 *
 * The test endpoint needs a saved row (POST /api/providers/{id}/test), so
 * "Test connection" saves first. If you then cancel an add, that row is
 * deleted again, so an abandoned attempt leaves nothing behind.
 */

import { useEffect, useMemo, useState } from "react";
import {
  api,
  type CustomModel,
  type Provider,
  type ProviderCreate,
  type ProviderPreset,
  type ProviderTestResult,
  type ProviderUpdate,
} from "../../api";
import { formatMs } from "../../format";
import { IconAlert, IconArrowLeft, IconCheck, IconExternal, IconPlus, IconSearch, IconTrash } from "../icons";
import { Badge, Button, Callout, Drawer, Field, Input, SecretInput, cx, toast } from "../ui";
import { ProviderMark } from "./meta";

/** Used when /api/providers/presets isn't answering: the spec's preset list. */
const FALLBACK_PRESETS: ProviderPreset[] = (
  [
    ["openai", "OpenAI", true, "openai"],
    ["anthropic", "Anthropic", true, "anthropic"],
    ["gemini", "Google Gemini", true, "openai"],
    ["sarvam", "Sarvam", false, "openai"],
    ["groq", "Groq", true, "openai"],
    ["openrouter", "OpenRouter", true, "openai"],
    ["deepseek", "DeepSeek", true, "openai"],
    ["mistral", "Mistral", true, "openai"],
    ["together", "Together AI", true, "openai"],
    ["fireworks", "Fireworks", true, "openai"],
    ["xai", "xAI", true, "openai"],
    ["nvidia", "NVIDIA", false, "openai"],
    ["azure_openai", "Azure OpenAI", true, "openai"],
    ["openai_compatible", "OpenAI-compatible", true, "openai"],
  ] as const
).map(([kind, label, tools, shape]) => ({
  kind,
  label,
  default_base_url: null,
  needs_base_url: kind === "azure_openai" || kind === "openai_compatible",
  key_url: null,
  supports_tools: tools,
  api_shape: shape,
  popular_models: [],
}));

interface ModelRow {
  id: string;
  name: string;
  input: string;
  output: string;
}

const toRow = (m: CustomModel): ModelRow => ({
  id: m.id,
  name: m.name,
  input: m.input_per_mtok === null ? "" : String(m.input_per_mtok),
  output: m.output_per_mtok === null ? "" : String(m.output_per_mtok),
});

const price = (text: string): number | null => {
  const n = Number(text);
  return text.trim() === "" || Number.isNaN(n) ? null : n;
};

type TestState = { phase: "idle" } | { phase: "testing" } | { phase: "done"; result: ProviderTestResult };

export function ProviderDrawer({
  open,
  onClose,
  presets,
  editing = null,
  initialKind = null,
  onSaved,
  onRemoved,
}: {
  open: boolean;
  onClose: () => void;
  presets: ProviderPreset[];
  /** Edit this row instead of adding one. */
  editing?: Provider | null;
  /** Skip the preset grid and start with this preset. */
  initialKind?: string | null;
  onSaved: (provider: Provider) => void;
  onRemoved?: (id: string) => void;
}) {
  const list = presets.length ? presets : FALLBACK_PRESETS;
  const [preset, setPreset] = useState<ProviderPreset | null>(null);
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showBaseUrl, setShowBaseUrl] = useState(false);
  const [models, setModels] = useState<ModelRow[]>([]);
  const [created, setCreated] = useState<Provider | null>(null);
  const [test, setTest] = useState<TestState>({ phase: "idle" });
  const [saving, setSaving] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // Reset every time the drawer opens.
  useEffect(() => {
    if (!open) return;
    const kind = editing?.kind ?? initialKind;
    const found = kind ? (list.find((p) => p.kind === kind) ?? null) : null;
    setPreset(found ?? (editing ? { ...FALLBACK_PRESETS[FALLBACK_PRESETS.length - 1], kind: editing.kind, label: editing.label } : null));
    setQuery("");
    setLabel(editing?.label ?? "");
    setKey("");
    setBaseUrl(editing?.base_url ?? "");
    setShowBaseUrl(!!editing?.base_url);
    setModels([]);
    setCreated(null);
    setTest({ phase: "idle" });
    setShowErrors(false);
    setFailure(null);
    if (editing) {
      api
        .providerModels(editing.id)
        .then((rows) =>
          setModels(
            rows
              .filter((m) => m.source === "custom")
              .map((m) => toRow({ id: m.id, name: m.name, input_per_mtok: m.input_per_mtok, output_per_mtok: m.output_per_mtok })),
          ),
        )
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing?.id, initialKind]);

  const target = editing ?? created;
  const needsBase = !!preset?.needs_base_url;
  const wantsModels = preset?.kind === "openai_compatible" || preset?.kind === "openrouter" || preset?.kind === "azure_openai";

  const errors = {
    key: !target && !key.trim() ? "Paste the API key." : null,
    base: needsBase && !baseUrl.trim() ? "This provider needs a base URL." : baseUrl.trim() && !/^https?:\/\/\S+$/i.test(baseUrl.trim()) ? "Use a full http(s) URL." : null,
    models: models.some((m) => !m.id.trim()) ? "Every custom model needs an id." : null,
  };
  const valid = !errors.key && !errors.base && !errors.models;

  const customModels: CustomModel[] = models
    .filter((m) => m.id.trim())
    .map((m) => ({ id: m.id.trim(), name: m.name.trim() || m.id.trim(), input_per_mtok: price(m.input), output_per_mtok: price(m.output) }));

  /** Create the row, or send what changed. */
  const persist = async (): Promise<Provider> => {
    if (!preset) throw new Error("Choose a provider first.");
    if (target) {
      const body: ProviderUpdate = { custom_models: customModels };
      if (label.trim() && label.trim() !== target.label) body.label = label.trim();
      if (key.trim()) body.api_key = key.trim();
      if ((baseUrl.trim() || null) !== (target.base_url || null)) body.base_url = baseUrl.trim() || null;
      return api.updateProvider(target.id, body);
    }
    const body: ProviderCreate = { kind: preset.kind, api_key: key.trim() };
    if (label.trim()) body.label = label.trim();
    if (baseUrl.trim()) body.base_url = baseUrl.trim();
    if (customModels.length) body.custom_models = customModels;
    const row = await api.createProvider(body);
    setCreated(row);
    setKey("");
    return row;
  };

  const runTest = async () => {
    setShowErrors(true);
    if (!valid) return;
    setTest({ phase: "testing" });
    setFailure(null);
    try {
      const row = await persist();
      const result = await api.testProvider(row.id);
      onSaved({ ...row, status: result.ok ? "ok" : "error", last_error: result.ok ? null : (result.error ?? null) });
      setTest({ phase: "done", result });
    } catch (err) {
      setTest({ phase: "done", result: { ok: false, latency_ms: null, model: null, error: (err as Error).message } });
    }
  };

  const save = async () => {
    setShowErrors(true);
    if (!valid) return;
    setSaving(true);
    setFailure(null);
    try {
      const row = await persist();
      const tested = test.phase === "done" ? test.result : null;
      onSaved(tested ? { ...row, status: tested.ok ? "ok" : "error" } : row);
      toast.success(editing ? `${row.label} updated` : `${row.label} added`, tested?.ok ? "Connection tested." : "Test it any time from its card.");
      setCreated(null);
      onClose();
    } catch (err) {
      setFailure((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    // An add that saved a row for testing and was then abandoned: remove it.
    if (created && !editing) {
      const id = created.id;
      api.deleteProvider(id).then(() => onRemoved?.(id)).catch(() => {});
    }
    onClose();
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? list.filter((p) => `${p.label} ${p.kind}`.toLowerCase().includes(q)) : list;
  }, [list, query]);

  const picking = !preset;

  return (
    <Drawer
      open={open}
      onClose={cancel}
      width="max-w-xl"
      title={editing ? `Edit ${editing.label}` : picking ? "Add a model provider" : `Add ${preset.label}`}
      description={picking ? "Any OpenAI- or Anthropic-shaped API. Keys are encrypted and never shown again." : "Keys are encrypted at rest and never returned by the API."}
      footer={
        picking ? (
          <div className="flex justify-end">
            <Button variant="secondary" onClick={cancel}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="ghost" onClick={cancel} disabled={saving} className="mr-auto">
              Cancel
            </Button>
            <Button variant="secondary" onClick={runTest} loading={test.phase === "testing"} disabled={saving}>
              Test connection
            </Button>
            <Button onClick={save} loading={saving} disabled={test.phase === "testing"}>
              {editing ? "Save changes" : "Save provider"}
            </Button>
          </div>
        )
      }
    >
      {picking ? (
        <div className="space-y-4 p-5">
          <label className="relative block">
            <span className="sr-only">Search providers</span>
            <IconSearch size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search providers" className="pl-9" data-autofocus />
          </label>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {filtered.map((p) => (
              <li key={p.kind}>
                <button
                  type="button"
                  onClick={() => {
                    setPreset(p);
                    setShowBaseUrl(p.needs_base_url);
                  }}
                  className="card card-interactive flex h-full w-full flex-col items-start gap-2.5 p-3 text-left"
                >
                  <ProviderMark kind={p.kind} label={p.label} />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-ink">{p.label}</span>
                    <span className="mt-0.5 block text-2xs text-ink-muted">
                      {p.kind === "openai_compatible" ? "Ollama, vLLM, LM Studio" : p.supports_tools ? "Tools supported" : "No tool calls"}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {filtered.length === 0 && <p className="py-4 text-center text-xs text-ink-muted">No provider matches “{query}”. Try OpenAI-compatible for any other endpoint.</p>}
        </div>
      ) : (
        <div className="space-y-5 p-5">
          <div className="flex items-center gap-3">
            <ProviderMark kind={preset.kind} label={preset.label} size="lg" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-ink">{preset.label}</p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <Badge tone={preset.supports_tools ? "good" : "neutral"}>{preset.supports_tools ? "Tools" : "No tools"}</Badge>
                <Badge tone="neutral">{preset.api_shape === "anthropic" ? "Anthropic API" : "OpenAI API"}</Badge>
              </div>
            </div>
            {!editing && !created && (
              <Button size="sm" variant="ghost" icon={<IconArrowLeft size={13} />} onClick={() => setPreset(null)}>
                Change
              </Button>
            )}
          </div>

          <Field label="Name" optional hint="How it's listed in model pickers.">
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={preset.label} />
          </Field>

          <Field
            label="API key"
            error={showErrors ? errors.key : null}
            hint={
              target?.key_hint ? (
                `Leave blank to keep the key ending ${target.key_hint}.`
              ) : preset.key_url ? (
                <a href={preset.key_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-brand hover:underline">
                  Get a {preset.label} key <IconExternal size={11} />
                </a>
              ) : preset.kind === "openai_compatible" ? (
                "Local servers often accept any value, like “ollama”."
              ) : undefined
            }
          >
            <SecretInput value={key} onChange={(e) => setKey(e.target.value)} placeholder={target?.key_hint ? `•••• ${target.key_hint}` : "sk-…"} aria-invalid={showErrors && !!errors.key} data-autofocus />
          </Field>

          {needsBase || showBaseUrl ? (
            <Field
              label="Base URL"
              optional={!needsBase}
              error={showErrors ? errors.base : null}
              hint={
                preset.kind === "openai_compatible"
                  ? "For example http://localhost:11434/v1 for Ollama. Private addresses need MCP_ALLOW_PRIVATE_HOSTS on the server."
                  : preset.kind === "azure_openai"
                    ? "Your resource's endpoint, e.g. https://my-resource.openai.azure.com."
                    : preset.default_base_url
                      ? `Defaults to ${preset.default_base_url}.`
                      : undefined
              }
            >
              <Input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={preset.default_base_url ?? "https://…/v1"} className="font-mono text-[0.8125rem]" />
            </Field>
          ) : (
            <button type="button" onClick={() => setShowBaseUrl(true)} className="text-xs font-medium text-brand hover:underline">
              Use a different base URL
            </button>
          )}

          <CustomModelsEditor rows={models} onChange={setModels} error={showErrors ? errors.models : null} emphasised={wantsModels} />

          {test.phase === "done" && <TestResult result={test.result} />}
          {failure && (
            <Callout tone="critical" title="Not saved">
              {failure}
            </Callout>
          )}
        </div>
      )}
    </Drawer>
  );
}

function TestResult({ result }: { result: ProviderTestResult }) {
  if (result.ok) {
    return (
      <Callout tone="good" title="Connected">
        {result.model ? `${result.model} answered` : "The provider answered"}
        {result.latency_ms != null && ` in ${formatMs(result.latency_ms)}`}.
      </Callout>
    );
  }
  const message = result.error ?? "The provider didn't answer.";
  const hint = /401|403|unauthori[sz]ed|invalid.*key|api key/i.test(message)
    ? "Check the key: it may be wrong, revoked, or for a different project."
    : /private|not allowed|ssrf|blocked/i.test(message)
      ? "The server refuses private addresses unless MCP_ALLOW_PRIVATE_HOSTS is set."
      : /timeout|timed out|connect/i.test(message)
        ? "Check the base URL and that the server is reachable from the backend."
        : null;
  return (
    <Callout tone="critical" title="The test failed">
      <span className="block break-words">{message}</span>
      {hint && <span className="mt-1 block text-ink-muted">{hint}</span>}
    </Callout>
  );
}

function CustomModelsEditor({
  rows,
  onChange,
  error,
  emphasised,
}: {
  rows: ModelRow[];
  onChange: (rows: ModelRow[]) => void;
  error: string | null;
  emphasised: boolean;
}) {
  const update = (i: number, patch: Partial<ModelRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () => onChange([...rows, { id: "", name: "", input: "", output: "" }]);

  return (
    <section aria-labelledby="custom-models" className={cx("rounded-xl border p-4", emphasised ? "border-line-strong" : "border-line")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id="custom-models" className="text-sm font-semibold text-ink">
            Custom models
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">
            Models that aren't in our price list. Prices are per 1M tokens in USD; leave them blank if you don't know and costs will read
            “unknown”, never $0.
          </p>
        </div>
        <Button size="sm" variant="secondary" icon={<IconPlus size={13} />} onClick={add}>
          Add
        </Button>
      </div>
      {rows.length > 0 && (
        <ul className="mt-3 space-y-2">
          {rows.map((row, i) => (
            <li key={i} className="grid grid-cols-2 gap-2 rounded-lg bg-subtle/60 p-2.5 sm:grid-cols-[1.4fr_1fr_0.7fr_0.7fr_auto] sm:items-end">
              <Field label="Model id" className="col-span-2 sm:col-span-1">
                <Input value={row.id} onChange={(e) => update(i, { id: e.target.value })} placeholder="llama3.1:8b" className="font-mono text-[0.8125rem]" aria-invalid={!!error && !row.id.trim()} />
              </Field>
              <Field label="Name" className="col-span-2 sm:col-span-1">
                <Input value={row.name} onChange={(e) => update(i, { name: e.target.value })} placeholder="Llama 3.1 8B" />
              </Field>
              <Field label="$ in">
                <Input inputMode="decimal" value={row.input} onChange={(e) => update(i, { input: e.target.value })} placeholder="—" className="tnum" />
              </Field>
              <Field label="$ out">
                <Input inputMode="decimal" value={row.output} onChange={(e) => update(i, { output: e.target.value })} placeholder="—" className="tnum" />
              </Field>
              <Button
                size="sm"
                variant="ghost"
                icon={<IconTrash size={13} />}
                onClick={() => onChange(rows.filter((_, j) => j !== i))}
                aria-label={`Remove ${row.id || "model"}`}
                className="col-span-2 justify-self-end sm:col-span-1 sm:mb-0.5"
              >
                <span className="sm:sr-only">Remove</span>
              </Button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="mt-2 flex items-center gap-1 text-xs text-critical">
          <IconAlert size={12} /> {error}
        </p>
      )}
      {rows.length === 0 && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-ink-muted">
          <IconCheck size={12} /> None. The provider's catalog models are listed automatically.
        </p>
      )}
    </section>
  );
}
