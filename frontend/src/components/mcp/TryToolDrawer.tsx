/**
 * "Try it": run one tool by hand before trusting the agent with it. The form
 * is built from the tool's input schema (see ./schema), with a JSON editor
 * for anything a form can't express — and a switch to JSON at any time.
 */

import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useReducedMotion } from "framer-motion";
import { api, type McpServer, type McpTool, type McpToolTestResult } from "../../api";
import { formatJson, formatMs, prettyText } from "../../format";
import { IconAlert, IconBraces, IconCheck, IconPlay, IconRows } from "../icons";
import {
  Badge,
  Button,
  Callout,
  CodeBlock,
  Drawer,
  Eyebrow,
  Field,
  Input,
  Segmented,
  Select,
  Switch,
  Textarea,
  cx,
  inputClass,
  toast,
} from "../ui";
import {
  buildArgs,
  draftFromArgs,
  initialDraft,
  parseArgs,
  planForm,
  type Arguments,
  type Draft,
  type SchemaField,
} from "./schema";
import { toolTitle } from "./toolText";

export function TryToolDrawer({
  server,
  tool,
  onClose,
}: {
  server: McpServer;
  tool: McpTool | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      open={!!tool}
      onClose={onClose}
      title={tool ? `Try ${toolTitle(tool.name)}` : "Try a tool"}
      description={tool ? `${server.name} · ${tool.name}` : undefined}
      width="max-w-xl"
    >
      {tool && <ToolRunner key={tool.id} server={server} tool={tool} />}
    </Drawer>
  );
}

type Mode = "form" | "json";

function ToolRunner({ server, tool }: { server: McpServer; tool: McpTool }) {
  const plan = useMemo(() => planForm(tool.input_schema), [tool.input_schema]);
  const fields = plan.mode === "form" ? plan.fields : [];

  const [mode, setMode] = useState<Mode>(plan.mode === "json" ? "json" : "form");
  const [draft, setDraft] = useState<Draft>(() => initialDraft(fields));
  const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set());
  const [jsonText, setJsonText] = useState(() =>
    plan.mode === "form" ? formatJson(buildArgs(fields, initialDraft(fields), new Set()).args) : "{}",
  );
  const [showErrors, setShowErrors] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<McpToolTestResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (result || runError) {
      outcomeRef.current?.scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
    }
  }, [result, runError, reduceMotion]);

  const built = buildArgs(fields, draft, touched);
  const parsed = parseArgs(jsonText);
  const jsonError = "error" in parsed ? parsed.error : null;

  const setField = (key: string, value: string | boolean) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setTouched((t) => new Set(t).add(key));
  };

  const switchMode = (next: Mode) => {
    setSwitchError(null);
    if (next === "json") {
      setJsonText(formatJson(built.args));
      setMode("json");
      return;
    }
    if ("error" in parsed) {
      setSwitchError("Fix the JSON before switching back to the form.");
      return;
    }
    setDraft(draftFromArgs(fields, parsed.args));
    setTouched(new Set(Object.keys(parsed.args)));
    setMode("form");
  };

  const run = async (event: FormEvent) => {
    event.preventDefault();
    let args: Arguments;
    if (mode === "json" || plan.mode === "json") {
      if ("error" in parsed) return;
      args = parsed.args;
    } else {
      setShowErrors(true);
      if (Object.keys(built.errors).length) return;
      args = built.args;
    }
    setRunning(true);
    setRunError(null);
    try {
      const outcome = await api.testMcpTool(server.id, tool.name, args);
      setResult(outcome);
      if (outcome.ok) toast.success(`${toolTitle(tool.name)} ran`, `Answered in ${formatMs(outcome.duration_ms)}.`);
      else toast.error(`${toolTitle(tool.name)} reported an error`, "The details are under Result.");
    } catch (err) {
      const message = (err as Error).message;
      setRunError(message);
      toast.error("Couldn't run the tool", message);
    } finally {
      setRunning(false);
    }
  };

  const formErrors = showErrors ? built.errors : {};
  const blocked = (mode === "json" || plan.mode === "json") && !!jsonError;

  return (
    <form onSubmit={run} className="flex min-h-full flex-col" noValidate>
      <div className="flex-1 space-y-5 px-5 py-5">
        {tool.description && <p className="text-sm leading-relaxed text-ink-secondary">{tool.description}</p>}

        <Callout tone="warning">
          This runs the tool for real on <span className="font-medium text-ink">{server.name}</span> — anything it books,
          sends or creates will actually happen.
        </Callout>

        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <Eyebrow>Arguments</Eyebrow>
            {plan.mode === "form" && (
              <Segmented
                label="Edit arguments as"
                size="sm"
                value={mode}
                onChange={switchMode}
                options={[
                  { value: "form", label: "Form", icon: <IconRows size={13} /> },
                  { value: "json", label: "JSON", icon: <IconBraces size={13} /> },
                ]}
              />
            )}
          </div>

          {switchError && (
            <p role="alert" className="flex items-center gap-1.5 text-xs text-critical">
              <IconAlert size={12} /> {switchError}
            </p>
          )}

          {plan.mode === "none" ? (
            <p className="rounded-lg border border-dashed border-line-strong px-4 py-3 text-xs text-ink-muted">
              This tool takes no inputs — just run it.
            </p>
          ) : mode === "json" || plan.mode === "json" ? (
            <JsonEditor
              value={jsonText}
              onChange={setJsonText}
              error={jsonError}
              note={plan.mode === "json" ? plan.reason : undefined}
            />
          ) : (
            <div className="space-y-4">
              {fields.map((field) => (
                <SchemaInput
                  key={field.key}
                  field={field}
                  value={draft[field.key]}
                  error={formErrors[field.key]}
                  onChange={(value) => setField(field.key, value)}
                />
              ))}
            </div>
          )}
        </section>

        {/* Below a long form the outcome would land off-screen: bring it into view. */}
        <div ref={outcomeRef} className="scroll-mb-20 space-y-5 empty:hidden">
          {runError && (
            <Callout tone="critical" title="The request failed">
              {runError}
            </Callout>
          )}
          {result && <ResultPanel result={result} />}
        </div>
      </div>

      <div className="safe-bottom sticky bottom-0 flex items-center justify-between gap-3 border-t border-line bg-raised px-5 py-3">
        <p className="min-w-0 text-xs text-ink-muted">
          {result ? `Last run ${result.ok ? "succeeded" : "failed"} in ${formatMs(result.duration_ms)}` : "Nothing run yet"}
        </p>
        <Button type="submit" loading={running} disabled={blocked} icon={<IconPlay size={12} />}>
          {running ? "Running…" : result ? "Run again" : "Run tool"}
        </Button>
      </div>
    </form>
  );
}

function SchemaInput({
  field,
  value,
  error,
  onChange,
}: {
  field: SchemaField;
  value: string | boolean | undefined;
  error: string | undefined;
  onChange: (value: string | boolean) => void;
}) {
  const text = typeof value === "string" ? value : "";

  if (field.kind === "boolean") {
    return (
      <Switch
        checked={value === true}
        onChange={onChange}
        label={
          <>
            {field.label}
            {!field.required && <span className="ml-1.5 text-xs font-normal text-ink-muted">Optional</span>}
          </>
        }
        description={field.description || undefined}
      />
    );
  }

  const common = {
    value: text,
    placeholder: field.placeholder,
    "aria-invalid": !!error,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
  };

  let control: ReactNode;
  switch (field.kind) {
    case "enum":
      control = (
        <Select value={text} onChange={(e) => onChange(e.target.value)} aria-invalid={!!error}>
          <option value="">{field.required ? "Choose…" : "Not set"}</option>
          {field.options.map((option, i) => (
            <option key={i} value={String(i)}>
              {String(option)}
            </option>
          ))}
        </Select>
      );
      break;
    case "number":
    case "integer":
      control = (
        <Input
          {...common}
          type="number"
          inputMode={field.kind === "integer" ? "numeric" : "decimal"}
          step={field.kind === "integer" ? 1 : "any"}
          min={field.schema.minimum}
          max={field.schema.maximum}
          className="tnum"
        />
      );
      break;
    case "date":
      control = <Input {...common} type="date" />;
      break;
    case "text":
      control = <Textarea {...common} className="min-h-20" />;
      break;
    case "json":
      control = <Textarea {...common} spellCheck={false} className="min-h-20 font-mono text-xs" />;
      break;
    default:
      control = <Input {...common} />;
  }

  return (
    <Field
      label={
        <span className="flex items-center gap-1.5">
          {field.label}
          {field.kind === "json" && <Badge tone="neutral">JSON</Badge>}
        </span>
      }
      optional={!field.required}
      hint={field.description || undefined}
      error={error}
    >
      {control}
    </Field>
  );
}

function JsonEditor({
  value,
  onChange,
  error,
  note,
}: {
  value: string;
  onChange: (value: string) => void;
  error: string | null;
  note?: string;
}) {
  return (
    <div className="space-y-2">
      {note && <p className="text-xs leading-relaxed text-ink-muted">{note}</p>}
      <label className="block">
        <span className="sr-only">Arguments as JSON</span>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          rows={Math.min(16, Math.max(6, value.split("\n").length + 1))}
          aria-invalid={!!error}
          className={cx(inputClass, "resize-y py-2 font-mono text-xs leading-relaxed")}
        />
      </label>
      {error ? (
        <p role="alert" className="flex items-start gap-1.5 text-xs text-critical">
          <IconAlert size={12} className="mt-0.5 shrink-0" /> {error}
        </p>
      ) : (
        <p className="flex items-center gap-1.5 text-xs text-good">
          <IconCheck size={12} /> Valid JSON
        </p>
      )}
    </div>
  );
}

function ResultPanel({ result }: { result: McpToolTestResult }) {
  return (
    <section aria-live="polite" className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>Result</Eyebrow>
        <span className="flex items-center gap-2">
          <span className="tnum text-xs text-ink-muted">{formatMs(result.duration_ms)}</span>
          {result.ok ? (
            <Badge tone="good" icon={<IconCheck size={11} />}>
              Succeeded
            </Badge>
          ) : (
            <Badge tone="critical" icon={<IconAlert size={11} />}>
              Tool error
            </Badge>
          )}
        </span>
      </div>
      {result.text ? (
        <CodeBlock copyLabel="Result" className={cx("max-h-80", !result.ok && "border-critical/30")}>
          {prettyText(result.text)}
        </CodeBlock>
      ) : (
        <p className="text-xs text-ink-muted">The tool returned no text.</p>
      )}
    </section>
  );
}
