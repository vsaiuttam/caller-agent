/**
 * Edit a connected server. Its URL and header values are write-only — the
 * API never returns them — so they can be replaced, never viewed. Replacing
 * either re-runs discovery.
 */

import { useEffect, useId, useState, type FormEvent } from "react";
import { ApiError, api, type McpServer, type McpServerUpdate } from "../../api";
import { IconLock } from "../icons";
import { Button, Callout, Dialog, Field, Input, SecretInput, toast } from "../ui";
import { HeaderRows, headerRow, headersFromRows, type HeaderRow } from "./HeaderRows";
import { checkServerUrl, connectHint } from "./meta";

export function EditServerDialog({
  server,
  open,
  onClose,
  onSaved,
}: {
  server: McpServer;
  open: boolean;
  onClose: () => void;
  onSaved: (server: McpServer) => void;
}) {
  const formId = useId();
  const [name, setName] = useState(server.name);
  const [url, setUrl] = useState<string | null>(null);
  const [rows, setRows] = useState<HeaderRow[] | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<{ message: string; hint: string | null } | null>(null);

  // Fresh form on every opening.
  useEffect(() => {
    if (!open) return;
    setName(server.name);
    setUrl(null);
    setRows(null);
    setShowErrors(false);
    setFailure(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const builtin = server.transport === "builtin";
  const urlCheck = url === null ? {} : checkServerUrl(url);
  const headerCheck = rows === null ? null : headersFromRows(rows);
  const nameError = name.trim() ? null : "Give it a name.";

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setShowErrors(true);
    if (nameError || urlCheck.error || headerCheck?.error) return;

    const body: McpServerUpdate = {};
    if (name.trim() !== server.name) body.name = name.trim();
    if (url !== null) body.url = url.trim();
    if (headerCheck) body.headers = headerCheck.headers;
    if (!Object.keys(body).length) {
      onClose();
      return;
    }

    const rediscover = body.url !== undefined || body.headers !== undefined;
    setSaving(true);
    setFailure(null);
    try {
      const updated = await api.updateMcpServer(server.id, body);
      onSaved(updated);
      if (rediscover && updated.status === "error") {
        // Saved, but it doesn't connect: stay open so the fix is one edit away.
        const message = updated.last_error ?? "The server didn't answer.";
        setFailure({ message, hint: connectHint(message) });
        setUrl(null);
        setRows(null);
        toast.error(`Saved, but ${updated.name} didn't connect`, message);
        return;
      }
      toast.success(
        `${updated.name} saved`,
        rediscover ? `Re-checked — ${updated.tools.length} ${updated.tools.length === 1 ? "tool" : "tools"} available.` : undefined,
      );
      onClose();
    } catch (err) {
      const message = (err as Error).message;
      setFailure({ message, hint: connectHint(message, err instanceof ApiError ? err.status : undefined) });
      toast.error("Couldn't save the server", message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Edit ${server.name}`}
      description={builtin ? "Built in — only its name can change." : "Secrets can be replaced, never viewed. Replacing either re-checks the connection."}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={saving}>
            {url !== null || rows !== null ? "Save & re-check" : "Save"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={save} noValidate className="space-y-5">
        {failure && (
          <Callout tone="critical" title="It didn't connect">
            <span className="block">{failure.message}</span>
            {failure.hint && <span className="mt-1.5 block text-ink">{failure.hint}</span>}
          </Callout>
        )}

        <Field label="Name" error={showErrors ? nameError : null}>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} aria-invalid={showErrors && !!nameError} />
        </Field>

        {!builtin && (
          <Field label="Server URL" group hint={url === null ? undefined : urlCheck.warning} error={showErrors ? urlCheck.error : null}>
            {url === null ? (
              <SavedSecret
                summary={server.host}
                note="Saved — hidden for security."
                action="Replace URL"
                onReplace={() => setUrl("")}
              />
            ) : (
              <div className="flex items-center gap-2">
                <SecretInput
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://…"
                  inputMode="url"
                  aria-label="New server URL"
                  aria-invalid={showErrors && !!urlCheck.error}
                  autoFocus
                  className="min-w-0 flex-1"
                />
                <Button variant="ghost" size="sm" onClick={() => setUrl(null)}>
                  Keep current
                </Button>
              </div>
            )}
          </Field>
        )}

        {!builtin && (
          <Field
            label="Headers"
            group
            hint={
              rows === null
                ? undefined
                : "Saving replaces every saved header with these. Remove them all to send none."
            }
            error={showErrors ? headerCheck?.error : null}
          >
            {rows === null ? (
              <SavedSecret
                summary={server.header_names.length ? server.header_names.join(", ") : "None"}
                note={server.header_names.length ? "Values hidden for security." : "Nothing is sent with requests."}
                action={server.header_names.length ? "Replace headers" : "Add headers"}
                onReplace={() =>
                  setRows(server.header_names.length ? server.header_names.map((n) => headerRow(n)) : [headerRow()])
                }
              />
            ) : (
              <div className="space-y-2">
                <HeaderRows rows={rows} onChange={setRows} />
                <Button variant="ghost" size="sm" onClick={() => setRows(null)}>
                  Keep current headers
                </Button>
              </div>
            )}
          </Field>
        )}
      </form>
    </Dialog>
  );
}

/** A saved secret: what can be said about it, and a way to replace it. */
function SavedSecret({
  summary,
  note,
  action,
  onReplace,
}: {
  summary: string;
  note: string;
  action: string;
  onReplace: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-subtle/50 px-3.5 py-2.5">
      <div className="flex min-w-0 items-center gap-2.5">
        <IconLock size={14} className="shrink-0 text-ink-muted" />
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-ink">{summary}</p>
          <p className="text-2xs text-ink-muted">{note}</p>
        </div>
      </div>
      <Button variant="secondary" size="sm" onClick={onReplace}>
        {action}
      </Button>
    </div>
  );
}
