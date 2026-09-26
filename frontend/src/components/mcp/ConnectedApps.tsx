/**
 * Integrations → Connected apps: the MCP servers the agent can reach, each
 * with its health, its tools, and a way to try any of them by hand.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, type McpServer, type McpTool } from "../../api";
import { useHealth } from "../../data";
import { formatRelative } from "../../format";
import { IconChevronDown, IconLock, IconPencil, IconPlay, IconPlug, IconRefresh, IconSparkle, IconTrash } from "../icons";
import {
  Badge,
  Button,
  Callout,
  Card,
  Dialog,
  EmptyState,
  ErrorNote,
  Skeleton,
  Switch,
  cx,
  toast,
} from "../ui";
import { ConnectDialog, type ConnectIntent } from "./ConnectDialog";
import { EditServerDialog } from "./EditServerDialog";
import { TRANSPORT_LABEL, connectHint, serverIcon } from "./meta";
import { ToolSummaryList } from "./ToolSummaryList";
import { TryToolDrawer } from "./TryToolDrawer";

const plural = (n: number, one: string) => `${n} ${n === 1 ? one : `${one}s`}`;

function useMcpServers() {
  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unsupported, setUnsupported] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setServers(await api.mcpServers());
      setUnsupported(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setUnsupported(true);
      else setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const upsert = useCallback(
    (server: McpServer) =>
      setServers((prev) =>
        prev?.some((s) => s.id === server.id) ? prev.map((s) => (s.id === server.id ? server : s)) : [...(prev ?? []), server],
      ),
    [],
  );
  const remove = useCallback((id: string) => setServers((prev) => prev?.filter((s) => s.id !== id) ?? null), []);

  return { servers, error, unsupported, reload: load, upsert, remove };
}

export function ConnectedApps({
  connect,
  onConnect,
}: {
  /** Whether (and how) the connect dialog is open — owned by the page so its header can open it. */
  connect: ConnectIntent | null;
  onConnect: (intent: ConnectIntent | null) => void;
}) {
  const { health, reload: reloadHealth } = useHealth();
  const { servers, error, unsupported, reload, upsert, remove } = useMcpServers();

  // The health payload counts enabled servers (the Overview checklist reads it).
  const saved = (server: McpServer) => {
    upsert(server);
    reloadHealth();
  };
  const removed = (id: string) => {
    remove(id);
    reloadHealth();
  };

  if (unsupported) {
    return (
      <Callout tone="info" title="This server doesn't support connected apps yet">
        Connected apps need a backend with MCP support (<code className="font-mono text-2xs">/api/mcp/servers</code>). Update the
        server, then come back here.
      </Callout>
    );
  }

  return (
    <div className="space-y-4">
      {health?.provider_supports_tools === false && (
        <Callout tone="warning" title={`${health.provider_label || "The active model provider"} can't use tools`}>
          Calls still run, just without tools. Switch the model provider to Anthropic, OpenAI or Gemini to let the agent use
          your connected apps.
        </Callout>
      )}
      {health?.secrets_sealed === false && (
        <Callout tone="warning" title="Server URLs and keys are stored unencrypted">
          Set <code className="font-mono text-2xs">SECRETS_KEY</code> on the server and restart to encrypt them at rest.
        </Callout>
      )}

      {error && !servers ? (
        <ErrorNote title="Couldn't load your connected apps" message={error} onRetry={reload} />
      ) : !servers ? (
        <div className="space-y-3" aria-busy="true" aria-label="Loading connected apps">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : servers.length === 0 ? (
        <Card>
          <EmptyState
            avatar="idle"
            title="Give the agent your tools"
            hint="Connect your CRM, calendar or helpdesk over MCP, and the agent can check availability, look people up and log outcomes — during the call and after it. Start with the built-in Demo CRM: no account needed."
            action={
              <>
                <Button icon={<IconSparkle size={14} />} onClick={() => onConnect("demo")}>
                  Try the Demo CRM
                </Button>
                <Button variant="secondary" icon={<IconPlug size={14} />} onClick={() => onConnect("pick")}>
                  Connect an app
                </Button>
              </>
            }
          />
        </Card>
      ) : (
        <>
          <ul className="space-y-3" aria-label="Connected apps">
            {servers.map((server) => (
              <li key={server.id}>
                <ServerCard server={server} onChange={saved} onRemoved={removed} />
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-muted">
            Connecting an app doesn't hand it to every call — each campaign chooses its tools on its own page.{" "}
            <Link to="/app/campaigns" className="font-medium text-brand hover:underline">
              Go to campaigns
            </Link>
          </p>
        </>
      )}

      <ConnectDialog
        intent={connect}
        servers={servers ?? []}
        onClose={() => onConnect(null)}
        onSaved={saved}
        onRemoved={removed}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------

function ServerStatusBadge({ server, checking }: { server: McpServer; checking: boolean }) {
  if (checking) {
    return (
      <Badge tone="info" dot pulse>
        Checking…
      </Badge>
    );
  }
  if (!server.enabled) return <Badge tone="neutral">Off</Badge>;
  if (server.status === "ok") {
    return (
      <Badge tone="good" dot>
        Connected
      </Badge>
    );
  }
  if (server.status === "error") return <Badge tone="critical">Error</Badge>;
  return <Badge tone="neutral">Not checked</Badge>;
}

function ServerCard({
  server,
  onChange,
  onRemoved,
}: {
  server: McpServer;
  onChange: (server: McpServer) => void;
  onRemoved: (id: string) => void;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [enabled, setEnabled] = useState<boolean | null>(null); // optimistic, while saving
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [trying, setTrying] = useState<McpTool | null>(null);
  const [open, setOpen] = useState(server.tools.length > 0 && server.tools.length <= 5);

  const on = enabled ?? server.enabled;
  const count = server.tools.length;
  const hint = server.status === "error" && server.last_error ? connectHint(server.last_error) : null;

  const refresh = async () => {
    setRefreshing(true);
    try {
      const updated = await api.refreshMcpServer(server.id);
      onChange(updated);
      if (updated.status === "ok") toast.success(`${updated.name} is connected`, `${plural(updated.tools.length, "tool")} available.`);
      else toast.error(`${updated.name} didn't answer`, updated.last_error ?? undefined);
    } catch (err) {
      toast.error(`Couldn't re-check ${server.name}`, (err as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  const toggle = async (next: boolean) => {
    setEnabled(next);
    try {
      onChange(await api.updateMcpServer(server.id, { enabled: next }));
      toast.success(
        `${server.name} turned ${next ? "on" : "off"}`,
        next ? "Campaigns that chose its tools can use them again." : "Calls skip its tools until you turn it back on.",
      );
    } catch (err) {
      toast.error(`Couldn't turn ${server.name} ${next ? "on" : "off"}`, (err as Error).message);
    } finally {
      setEnabled(null);
    }
  };

  return (
    <Card className="overflow-hidden">
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <div className="flex min-w-0 items-start gap-3">
            <span
              className={cx(
                "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                on && server.status === "ok" ? "bg-good/12 text-good" : "bg-subtle text-ink-muted",
              )}
            >
              {serverIcon(server)}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-sm font-semibold text-ink">{server.name}</h3>
                <ServerStatusBadge server={server} checking={refreshing} />
              </div>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-ink-muted">
                <span className="truncate font-mono">{server.host}</span>
                <span aria-hidden>·</span>
                <span>{TRANSPORT_LABEL[server.transport]}</span>
                <span aria-hidden>·</span>
                <span className="tnum">{plural(count, "tool")}</span>
                <span aria-hidden>·</span>
                <span>{server.checked_at ? `checked ${formatRelative(server.checked_at)}` : "never checked"}</span>
              </p>
              {server.header_names.length > 0 && (
                <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {server.header_names.map((name) => (
                    <span
                      key={name}
                      className="inline-flex items-center gap-1 rounded border border-line bg-subtle/60 px-1.5 py-0.5 font-mono text-2xs text-ink-secondary"
                      title="Value hidden — replace it with Edit"
                    >
                      <IconLock size={10} /> {name}
                    </span>
                  ))}
                </p>
              )}
            </div>
          </div>
          <Switch
            checked={on}
            onChange={(next) => void toggle(next)}
            disabled={enabled !== null}
            label={
              <>
                Enabled<span className="sr-only"> — {server.name}</span>
              </>
            }
            className="items-center gap-2.5"
          />
        </div>

        {server.status === "error" && !refreshing && (
          <Callout tone="critical" title="Couldn't connect" className="mt-3.5">
            <span className="block break-words">{server.last_error ?? "The server didn't answer."}</span>
            {hint && <span className="mt-1 block text-ink">{hint}</span>}
          </Callout>
        )}

        <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
          <Button size="sm" variant="secondary" icon={<IconRefresh size={13} />} loading={refreshing} onClick={refresh}>
            {refreshing ? "Checking…" : "Refresh"}
          </Button>
          <Button size="sm" variant="ghost" icon={<IconPencil size={13} />} onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button size="sm" variant="ghost" icon={<IconTrash size={13} />} onClick={() => setRemoving(true)} className="text-critical hover:text-critical">
            Remove
          </Button>
          {count > 0 && (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              className="ml-auto inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs font-medium text-ink-secondary transition-colors hover:bg-subtle hover:text-ink"
            >
              {open ? "Hide tools" : `Show ${plural(count, "tool")}`}
              <IconChevronDown size={13} className={cx("transition-transform", open && "rotate-180")} />
            </button>
          )}
        </div>
      </div>

      {open && count > 0 && (
        <div className="border-t border-line bg-subtle/30 px-5 py-4">
          <ToolSummaryList
            tools={server.tools}
            className="bg-surface"
            action={(tool) => (
              <Button
                size="sm"
                variant="secondary"
                icon={<IconPlay size={10} />}
                onClick={() => setTrying(tool)}
                disabled={server.status !== "ok"}
                aria-label={`Try ${tool.name}`}
              >
                Try it
              </Button>
            )}
          />
        </div>
      )}

      <EditServerDialog server={server} open={editing} onClose={() => setEditing(false)} onSaved={onChange} />
      <RemoveDialog server={server} open={removing} onClose={() => setRemoving(false)} onRemoved={onRemoved} />
      <TryToolDrawer server={server} tool={trying} onClose={() => setTrying(null)} />
    </Card>
  );
}

function RemoveDialog({
  server,
  open,
  onClose,
  onRemoved,
}: {
  server: McpServer;
  open: boolean;
  onClose: () => void;
  onRemoved: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteMcpServer(server.id);
      toast.success(`${server.name} removed`, "Its tools were taken off every campaign that used them.");
      onClose();
      onRemoved(server.id);
    } catch (err) {
      toast.error(`Couldn't remove ${server.name}`, (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="sm"
      title={`Remove ${server.name}?`}
      description={`The agent loses its ${plural(server.tools.length, "tool")} straight away, and they're taken off every campaign that uses them. The saved URL and keys are deleted.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy} data-autofocus>
            Cancel
          </Button>
          <Button variant="danger" onClick={remove} loading={busy}>
            Remove
          </Button>
        </>
      }
    />
  );
}
