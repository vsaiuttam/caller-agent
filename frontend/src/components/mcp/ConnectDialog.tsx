/**
 * "Connect an app": pick a preset (the built-in Demo CRM is one click),
 * paste a URL and any key, and watch the server get discovered. Saving and
 * discovery are one request; a server that fails discovery is still saved,
 * so the user can fix it here or later from its card.
 */

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type McpServer, type McpServerCreate, type McpTransportChoice } from "../../api";
import { useHealth } from "../../data";
import { IconArrowRight, IconCheck, IconChevronRight } from "../icons";
import { Badge, Button, Callout, Dialog, Field, Input, Segmented, SecretInput, cx, toast } from "../ui";
import { HeaderRows, headersFromRows, type HeaderRow } from "./HeaderRows";
import { DEMO_URL, PRESETS, checkServerUrl, connectHint, type Preset } from "./meta";
import { ToolSummaryList } from "./ToolSummaryList";

/** Why the dialog opened: to choose a preset, or straight into the demo. */
export type ConnectIntent = "pick" | "demo";

type Step = "pick" | "form" | "connecting" | "done";

interface ServerDraft {
  name: string;
  url: string;
  transport: McpTransportChoice;
  rows: HeaderRow[];
}

interface Failure {
  message: string;
  hint: string | null;
}

const DEMO = PRESETS[0];
const CUSTOM = PRESETS[PRESETS.length - 1];
const EMPTY: ServerDraft = { name: "", url: "", transport: "auto", rows: [] };

function validate(draft: ServerDraft) {
  const url = checkServerUrl(draft.url);
  const headers = headersFromRows(draft.rows);
  return {
    name: draft.name.trim() ? null : "Give it a name, e.g. “Calendar”.",
    url: url.error ?? null,
    urlWarning: url.warning ?? null,
    headers: headers.error,
    headerValues: headers.headers,
  };
}

const hostOf = (url: string) => {
  try {
    return new URL(url).host || url;
  } catch {
    return url;
  }
};

export function ConnectDialog({
  intent,
  servers,
  onClose,
  onSaved,
  onRemoved,
}: {
  /** Null while closed. */
  intent: ConnectIntent | null;
  servers: McpServer[];
  onClose: () => void;
  onSaved: (server: McpServer) => void;
  onRemoved: (id: string) => void;
}) {
  const formId = useId();
  const [step, setStep] = useState<Step>("pick");
  const [preset, setPreset] = useState<Preset>(CUSTOM);
  const [draft, setDraft] = useState<ServerDraft>(EMPTY);
  const [showErrors, setShowErrors] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  /** What this attempt saved — kept after a failed discovery so a retry replaces it. */
  const [saved, setSaved] = useState<McpServer | null>(null);

  const connect = async (target: Preset, body: McpServerCreate) => {
    setPreset(target);
    setStep("connecting");
    setFailure(null);
    try {
      // A retry starts clean: the half-configured server from the last
      // attempt goes, so the list never collects broken duplicates.
      if (saved) {
        await api.deleteMcpServer(saved.id);
        onRemoved(saved.id);
        setSaved(null);
      }
      const server = await api.createMcpServer(body);
      onSaved(server);
      setSaved(server);
      if (server.status === "ok") {
        setStep("done");
        toast.success(`${server.name} connected`, `${server.tools.length} ${server.tools.length === 1 ? "tool" : "tools"} found.`);
        return;
      }
      const message = server.last_error ?? "The server didn't answer.";
      setFailure({ message, hint: connectHint(message) });
      setStep(target.id === "demo" ? "pick" : "form");
      toast.error(`Couldn't connect to ${server.name}`, message);
    } catch (err) {
      const message = (err as Error).message;
      setFailure({ message, hint: connectHint(message, err instanceof ApiError ? err.status : undefined) });
      setStep(target.id === "demo" ? "pick" : "form");
      toast.error("Couldn't connect", message);
    }
  };

  const connectDemo = () => void connect(DEMO, { name: DEMO.defaultName, url: DEMO_URL });

  // Every opening starts fresh; "demo" goes straight to connecting.
  useEffect(() => {
    if (!intent) return;
    setStep("pick");
    setPreset(CUSTOM);
    setDraft(EMPTY);
    setShowErrors(false);
    setFailure(null);
    setSaved(null);
    if (intent === "demo") connectDemo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent]);

  // Each step replaces the content under the focused element; move focus to
  // the new step so it never drops to <body> and out of the dialog.
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const id = requestAnimationFrame(() => body.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus());
    return () => cancelAnimationFrame(id);
  }, [step]);

  const choose = (next: Preset) => {
    if (next.id === "demo") {
      connectDemo();
      return;
    }
    setPreset(next);
    setDraft((d) => ({ ...d, name: d.name || next.defaultName }));
    setFailure(null);
    setShowErrors(false);
    setStep("form");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setShowErrors(true);
    const check = validate(draft);
    if (check.name || check.url || check.headers) return;
    void connect(preset, {
      name: draft.name.trim(),
      url: draft.url.trim(),
      transport: draft.transport,
      headers: check.headerValues,
    });
  };

  const heading: Record<Step, { title: string; description?: string }> = {
    pick: {
      title: "Connect an app",
      description: "Give the agent tools from your own systems over MCP — to look things up during calls and record outcomes after.",
    },
    form: { title: `Connect ${preset.title}` },
    connecting: { title: `Connecting to ${preset.id === "demo" ? "the Demo CRM" : hostOf(draft.url)}…` },
    done: { title: "Connected" },
  };

  const footer = {
    pick: (
      <Button variant="secondary" onClick={onClose}>
        Cancel
      </Button>
    ),
    form: (
      <>
        <Button variant="ghost" onClick={() => setStep("pick")}>
          Back
        </Button>
        <Button type="submit" form={formId}>
          {saved ? "Try again" : "Connect & discover"}
        </Button>
      </>
    ),
    connecting: (
      <>
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
        <Button loading>Connecting…</Button>
      </>
    ),
    done: (
      <>
        <Button
          variant="secondary"
          onClick={() => {
            setSaved(null);
            setDraft(EMPTY);
            setStep("pick");
          }}
        >
          Connect another
        </Button>
        <Button onClick={onClose}>Done</Button>
      </>
    ),
  }[step];

  return (
    <Dialog
      open={!!intent}
      onClose={onClose}
      size="lg"
      title={heading[step].title}
      description={heading[step].description}
      footer={footer}
    >
      <div ref={body}>
        {step === "pick" && (
          <PresetGrid
            demoConnected={servers.some((s) => s.transport === "builtin" && s.status === "ok")}
            demoFailure={preset.id === "demo" ? failure : null}
            onChoose={choose}
          />
        )}
        {step === "form" && (
          <ServerForm
            id={formId}
            preset={preset}
            draft={draft}
            onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
            onSubmit={submit}
            showErrors={showErrors}
            failure={failure}
            saved={saved}
          />
        )}
        {step === "connecting" && <ConnectProgress demo={preset.id === "demo"} />}
        {step === "done" && saved && <Connected server={saved} />}
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------

function PresetGrid({
  demoConnected,
  demoFailure,
  onChoose,
}: {
  demoConnected: boolean;
  demoFailure: Failure | null;
  onChoose: (preset: Preset) => void;
}) {
  return (
    <div className="space-y-3">
      {demoFailure && (
        <Callout tone="critical" title="The Demo CRM didn't start">
          {demoFailure.message}
        </Callout>
      )}
      <ul className="grid grid-cols-2 gap-2.5">
        {PRESETS.map((p, i) => {
          const done = p.id === "demo" && demoConnected;
          return (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => onChoose(p)}
                disabled={done}
                data-autofocus={(i === 0 && !done) || (i === 1 && done) || undefined}
                className={cx(
                  "card card-interactive flex h-full w-full flex-col items-start gap-2 p-3.5 text-left disabled:cursor-default disabled:opacity-70",
                  p.id === "demo" && !done && "border-brand/35 bg-brand/[0.03]",
                )}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-subtle text-ink-secondary">{p.icon}</span>
                  {done ? (
                    <Badge tone="good" icon={<IconCheck size={11} />}>
                      Connected
                    </Badge>
                  ) : p.id === "demo" ? (
                    <Badge tone="brand">One click</Badge>
                  ) : (
                    <IconChevronRight size={15} className="text-ink-muted" />
                  )}
                </span>
                <span className="text-sm font-semibold text-ink">{p.title}</span>
                <span className="text-xs leading-relaxed text-ink-muted">{p.tagline}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ServerForm({
  id,
  preset,
  draft,
  onChange,
  onSubmit,
  showErrors,
  failure,
  saved,
}: {
  id: string;
  preset: Preset;
  draft: ServerDraft;
  onChange: (patch: Partial<ServerDraft>) => void;
  onSubmit: (event: FormEvent) => void;
  showErrors: boolean;
  failure: Failure | null;
  saved: McpServer | null;
}) {
  const { health } = useHealth();
  const check = validate(draft);
  const errors = showErrors ? check : null;
  const sealed = health?.secrets_sealed !== false;

  return (
    <form id={id} onSubmit={onSubmit} noValidate className="space-y-4">
      {failure && (
        <Callout tone="critical" title={saved ? `Saved as “${saved.name}”, but it didn't connect` : "It didn't connect"}>
          <span className="block">{failure.message}</span>
          {failure.hint && <span className="mt-1.5 block text-ink">{failure.hint}</span>}
          {saved && <span className="mt-1.5 block">Fix the details and try again — or close this and fix it later from its card.</span>}
        </Callout>
      )}

      <div className="flex items-start gap-3 rounded-lg border border-line bg-subtle/50 px-3.5 py-3">
        <span className="mt-0.5 shrink-0 text-ink-secondary">{preset.icon}</span>
        <p className="text-xs leading-relaxed text-ink-secondary">{preset.where}</p>
      </div>

      <Field label="Name" error={errors?.name} hint="How it's labelled in campaigns and call logs.">
        <Input
          value={draft.name}
          onChange={(e) => onChange({ name: e.target.value })}
          maxLength={100}
          placeholder="Calendar"
          data-autofocus={!draft.name || undefined}
          aria-invalid={!!errors?.name}
        />
      </Field>

      <Field
        label="Server URL"
        error={errors?.url}
        hint={
          check.urlWarning ??
          (sealed
            ? "Stored encrypted, and never shown again — not even to you."
            : "Never shown again once saved. It's stored unencrypted until SECRETS_KEY is set on the server.")
        }
      >
        <SecretInput
          value={draft.url}
          onChange={(e) => onChange({ url: e.target.value })}
          placeholder={preset.urlPlaceholder}
          inputMode="url"
          data-autofocus={!!draft.name || undefined}
          aria-invalid={!!errors?.url}
        />
      </Field>

      <Field
        label="Headers"
        group
        optional
        hint="Usually one: Authorization with “Bearer <your key>”. Values are hidden once saved."
        error={errors?.headers}
      >
        <HeaderRows rows={draft.rows} onChange={(rows) => onChange({ rows })} />
      </Field>

      <details className="group rounded-lg border border-line">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-3.5 py-2.5 text-xs font-medium text-ink-secondary transition-colors hover:text-ink [&::-webkit-details-marker]:hidden">
          <IconChevronRight size={13} className="transition-transform group-open:rotate-90" />
          Advanced
        </summary>
        <div className="border-t border-line px-3.5 py-3">
          <Field label="Transport" group hint="Auto tries Streamable HTTP first, then falls back to SSE.">
            <Segmented
              label="Transport"
              value={draft.transport}
              onChange={(transport) => onChange({ transport })}
              options={[
                { value: "auto", label: "Auto" },
                { value: "streamable_http", label: "Streamable HTTP" },
                { value: "sse", label: "SSE" },
              ]}
            />
          </Field>
        </div>
      </details>
    </form>
  );
}

const STAGES = ["Checking the address is safe", "Connecting", "Listing its tools"];
const DEMO_STAGES = ["Starting the Demo CRM", "Listing its tools"];

/**
 * Saving, connecting and discovery are one request, so the stages advance on
 * a timer — they name what the server is doing, in the order it does it.
 */
function ConnectProgress({ demo }: { demo: boolean }) {
  const stages = demo ? DEMO_STAGES : STAGES;
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const timers = stages.slice(1).map((_, i) => window.setTimeout(() => setStage(i + 1), 700 * (i + 1)));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [stages]);

  return (
    <div
      aria-busy="true"
      aria-live="polite"
      tabIndex={-1}
      data-autofocus
      className="rounded-xl border border-line bg-subtle/40 px-4 py-4 outline-none"
    >
      <ol className="space-y-2.5">
        {stages.map((label, i) => (
          <li key={label} className="flex items-center gap-2.5 text-sm">
            <span
              className={cx(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                i < stage ? "bg-brand text-on-brand" : "border border-line-strong bg-surface",
              )}
              aria-hidden
            >
              {i < stage ? <IconCheck size={11} /> : i === stage && <span className="live-dot h-2 w-2 rounded-full bg-brand" />}
            </span>
            <span className={i <= stage ? "text-ink" : "text-ink-muted"}>
              {label}
              {i === stage && "…"}
            </span>
          </li>
        ))}
      </ol>
      {!demo && <p className="mt-3.5 text-xs text-ink-muted">A server gets about ten seconds to answer.</p>}
    </div>
  );
}

function Connected({ server }: { server: McpServer }) {
  const count = server.tools.length;
  return (
    <div className="space-y-4">
      <div
        tabIndex={-1}
        data-autofocus
        className="flex items-start gap-3 rounded-xl border border-good/25 bg-good/6 px-4 py-3.5 outline-none"
      >
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-good text-white">
          <IconCheck size={13} />
        </span>
        <div className="min-w-0 text-sm">
          <p className="font-medium text-ink">{server.name} is connected</p>
          <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">
            {count
              ? `${count} ${count === 1 ? "tool" : "tools"} found. The agent uses them only in campaigns where you allow them.`
              : "It answered, but offers no tools yet. Add some on the server's side, then press Refresh on its card."}
          </p>
        </div>
      </div>
      {count > 0 && <ToolSummaryList tools={server.tools} className="max-h-64 overflow-y-auto" />}
      <p className="text-xs text-ink-muted">
        Next, choose which tools each campaign may use —{" "}
        <Link to="/campaigns" className="inline-flex items-center gap-1 font-medium text-brand hover:underline">
          open a campaign <IconArrowRight size={12} />
        </Link>
      </p>
    </div>
  );
}
