/**
 * A campaign's tools: which connected-app tools the agent may use during the
 * call, and which after it to record the outcome — with plain-language
 * instructions for the latter. Controlled: the campaign page saves it with a
 * PATCH, the new-campaign form sends it with the create.
 */

import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type CampaignCreate, type McpToolOption } from "../../api";
import { useHealth } from "../../data";
import { useAsync } from "../../hooks";
import { IconPlug, IconSearch, IconWrench } from "../icons";
import {
  ButtonLink,
  Callout,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Segmented,
  Skeleton,
  Textarea,
  cx,
} from "../ui";
import { toolNameFromId, toolTitle } from "./toolText";

export type ToolChoice = Required<Pick<CampaignCreate, "mcp_tools" | "mcp_post_call_tools" | "mcp_post_call_instructions">>;

type Section = "in_call" | "post_call";

const EXAMPLE_INSTRUCTIONS =
  "If they agreed a time, book the appointment. If they asked for a callback or raised a problem, create a ticket with a one-line summary — priority high if they sounded upset. If the call went nowhere, record nothing.";

const EXPLAIN: Record<Section, string> = {
  in_call:
    "The agent can look things up and take actions mid-conversation. It says “let me check” first, so there's no dead air.",
  post_call:
    "When the call ends, the agent records the outcome in your apps with these tools. Skipped for calls held for review, and for no-answers and voicemails.",
};

/** Same selection and instructions, ignoring order. */
export function sameChoice(a: ToolChoice, b: ToolChoice): boolean {
  const same = (x: string[], y: string[]) => x.length === y.length && x.every((id) => y.includes(id));
  return (
    same(a.mcp_tools, b.mcp_tools) &&
    same(a.mcp_post_call_tools, b.mcp_post_call_tools) &&
    a.mcp_post_call_instructions === b.mcp_post_call_instructions
  );
}

export function CampaignToolsCard({
  value,
  onChange,
  action,
}: {
  value: ToolChoice;
  onChange: (next: ToolChoice) => void;
  /** Header actions, e.g. Save / Discard on a saved campaign. */
  action?: ReactNode;
}) {
  const catalog = useAsync(() => api.mcpTools(), []);
  const { health } = useHealth();
  const nothingChosen = !value.mcp_tools.length && !value.mcp_post_call_tools.length;

  let body: ReactNode;
  if (catalog.loading) {
    body = (
      <div className="space-y-2 px-5 py-4" aria-busy="true" aria-label="Loading tools">
        <Skeleton className="h-8 w-72 max-w-full" />
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
    );
  } else if (catalog.error) {
    body = (
      <div className="px-5 py-4">
        <ErrorNote title="Couldn't load your tools" message={catalog.error} onRetry={catalog.reload} />
      </div>
    );
  } else if (!catalog.data?.length && nothingChosen) {
    body = (
      <EmptyState
        compact
        avatar={false}
        icon={<IconPlug size={26} />}
        title="No connected apps yet"
        hint="Connect your CRM, calendar or helpdesk under Integrations — or the built-in Demo CRM — then choose here what this campaign's agent may use."
        action={
          <ButtonLink to="/settings?connect=1" size="sm" icon={<IconPlug size={13} />}>
            Connect an app
          </ButtonLink>
        }
      />
    );
  } else {
    body = <ToolChoiceEditor catalog={catalog.data ?? []} value={value} onChange={onChange} />;
  }

  return (
    <Card>
      <CardHeader
        title="Tools"
        subtitle="What the agent may use from your connected apps, during the call and after it."
        icon={<IconWrench size={15} />}
        action={action}
      />
      {health?.provider_supports_tools === false && (
        <div className="px-5 pt-4">
          <Callout tone="warning" title={`${health.provider_label || "The model provider"} can't use tools`}>
            Calls still run, just without them. Anthropic, OpenAI and Gemini can.
          </Callout>
        </div>
      )}
      {body}
    </Card>
  );
}

function ToolChoiceEditor({
  catalog,
  value,
  onChange,
}: {
  catalog: McpToolOption[];
  value: ToolChoice;
  onChange: (next: ToolChoice) => void;
}) {
  const [section, setSection] = useState<Section>("in_call");
  const [query, setQuery] = useState("");
  const selected = section === "in_call" ? value.mcp_tools : value.mcp_post_call_tools;
  const setSelected = (ids: string[]) =>
    onChange(section === "in_call" ? { ...value, mcp_tools: ids } : { ...value, mcp_post_call_tools: ids });
  const toggle = (id: string, on: boolean) => setSelected(on ? [...selected, id] : selected.filter((x) => x !== id));

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const byServer = new Map<string, { name: string; tools: McpToolOption[] }>();
    for (const tool of catalog) {
      const match = !q || [tool.name, tool.description, tool.server_name].some((t) => t.toLowerCase().includes(q));
      if (!match) continue;
      const group = byServer.get(tool.server_id) ?? { name: tool.server_name, tools: [] };
      group.tools.push(tool);
      byServer.set(tool.server_id, group);
    }
    return [...byServer.entries()];
  }, [catalog, query]);

  // Chosen before, but their app is off, failing or gone: calls skip them.
  const known = new Set(catalog.map((t) => t.id));
  const unavailable = selected.filter((id) => !known.has(id));

  return (
    <div className="space-y-4 px-5 py-4">
      <div className="space-y-2">
        <Segmented
          label="When the agent may use tools"
          value={section}
          onChange={setSection}
          className="w-full sm:w-auto [&>button]:flex-1"
          options={[
            { value: "in_call", label: <SectionLabel text="During the call" count={value.mcp_tools.length} /> },
            { value: "post_call", label: <SectionLabel text="After the call" count={value.mcp_post_call_tools.length} /> },
          ]}
        />
        <p className="text-xs leading-relaxed text-ink-muted">{EXPLAIN[section]}</p>
      </div>

      {catalog.length > 8 && (
        <label className="relative block">
          <span className="sr-only">Filter tools</span>
          <IconSearch size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter tools" className="pl-8" />
        </label>
      )}

      {groups.length === 0 && catalog.length > 0 && (
        <p className="py-3 text-center text-xs text-ink-muted">No tools match “{query}”.</p>
      )}
      {catalog.length === 0 && (
        <p className="rounded-lg border border-dashed border-line-strong px-4 py-3 text-xs leading-relaxed text-ink-muted">
          None of your connected apps is available right now — they're turned off or failing. Check them under{" "}
          <Link to="/settings" className="font-medium text-brand hover:underline">
            Integrations
          </Link>
          .
        </p>
      )}

      {groups.map(([serverId, group]) => {
        const ids = group.tools.map((t) => t.id);
        const chosen = ids.filter((id) => selected.includes(id)).length;
        const all = chosen === ids.length;
        const headingId = `tools-${section}-${serverId}`;
        return (
          <div key={serverId} role="group" aria-labelledby={headingId} className="space-y-1">
            <div className="flex items-center justify-between gap-3">
              <p id={headingId} className="text-2xs font-medium uppercase tracking-wider text-ink-muted">
                {group.name} <span className="tnum normal-case tracking-normal">· {chosen} of {ids.length}</span>
              </p>
              <button
                type="button"
                onClick={() => setSelected(all ? selected.filter((id) => !ids.includes(id)) : [...new Set([...selected, ...ids])])}
                aria-label={`${all ? "Clear" : "Select all"} ${group.name} tools`}
                className="rounded text-xs font-medium text-brand hover:underline"
              >
                {all ? "Clear" : "Select all"}
              </button>
            </div>
            <ul className="space-y-0.5">
              {group.tools.map((tool) => (
                <li key={tool.id}>
                  <ToolCheckbox
                    title={toolTitle(tool.name)}
                    name={tool.name}
                    description={tool.description}
                    checked={selected.includes(tool.id)}
                    onChange={(on) => toggle(tool.id, on)}
                  />
                </li>
              ))}
            </ul>
          </div>
        );
      })}

      {unavailable.length > 0 && (
        <div
          role="group"
          aria-labelledby={`tools-${section}-unavailable`}
          className="space-y-1 rounded-lg border border-warning/30 bg-warning/6 p-2"
        >
          <p id={`tools-${section}-unavailable`} className="px-1 text-2xs font-medium uppercase tracking-wider text-warning">
            Unavailable right now
          </p>
          <p className="px-1 text-xs leading-relaxed text-ink-secondary">
            Their app is turned off, failing or was removed, so calls skip them. Untick to drop them.
          </p>
          <ul className="space-y-0.5">
            {unavailable.map((id) => (
              <li key={id}>
                <ToolCheckbox
                  title={toolTitle(toolNameFromId(id))}
                  name={id}
                  description=""
                  checked
                  onChange={(on) => toggle(id, on)}
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {section === "post_call" && (
        <Field
          label="Instructions for after the call"
          optional
          hint={
            <>
              What to record, where, and when to leave things alone. The agent never invents data.
              {!value.mcp_post_call_instructions && (
                <>
                  {" "}
                  <button
                    type="button"
                    onClick={() => onChange({ ...value, mcp_post_call_instructions: EXAMPLE_INSTRUCTIONS })}
                    className="font-medium text-brand hover:underline"
                  >
                    Use the example
                  </button>
                </>
              )}
            </>
          }
        >
          <Textarea
            value={value.mcp_post_call_instructions}
            onChange={(e) => onChange({ ...value, mcp_post_call_instructions: e.target.value })}
            placeholder={EXAMPLE_INSTRUCTIONS}
            className="min-h-24"
          />
        </Field>
      )}
    </div>
  );
}

function SectionLabel({ text, count }: { text: string; count: number }) {
  return (
    <>
      {text}
      <span
        className={cx(
          "tnum inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px]",
          count ? "bg-brand/12 text-brand" : "bg-subtle-strong text-ink-muted",
        )}
      >
        {count}
      </span>
    </>
  );
}

function ToolCheckbox({
  title,
  name,
  description,
  checked,
  onChange,
}: {
  title: string;
  name: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label
      className={cx(
        "flex cursor-pointer items-start gap-3 rounded-lg px-2.5 py-2 transition-colors",
        checked ? "bg-brand/6" : "hover:bg-subtle/70",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--color-brand)]"
      />
      <span className="min-w-0">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium text-ink">{title}</span>
          <code className="break-all font-mono text-2xs text-ink-muted">{name}</code>
        </span>
        {description && <span className="mt-0.5 line-clamp-2 block text-xs leading-relaxed text-ink-secondary">{description}</span>}
      </span>
    </label>
  );
}
