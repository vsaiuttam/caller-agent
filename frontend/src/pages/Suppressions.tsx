import { useState } from "react";
import { api } from "../api";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Field,
  inputClass,
} from "../components/ui";
import { formatDateTime } from "../format";
import { useAsync } from "../hooks";

export default function Suppressions() {
  const { data, loading, error, reload } = useAsync(() => api.suppressions());
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const add = async () => {
    setBusy(true);
    setAddError(null);
    try {
      await api.addSuppression(phone.trim(), reason.trim() || "Manually added");
      setPhone("");
      setReason("");
      reload();
    } catch (err) {
      setAddError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-3 py-4 sm:px-6 sm:py-5">
      <header className="mb-5">
        <h1 className="text-xl font-bold tracking-tight">Do not call</h1>
        <p className="mt-0.5 text-sm text-ink-muted">
          Numbers here are never dialled, across every campaign.
        </p>
      </header>

      <Card className="mb-3">
        <CardHeader title="Add a number" />
        <div className="flex items-end gap-3 px-5 py-4">
          <div className="w-56">
            <Field label="Phone number" hint="E.164, e.g. +14155550123">
              <input
                className={inputClass}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+14155550123"
              />
            </Field>
          </div>
          <div className="flex-1">
            <Field label="Reason">
              <input
                className={inputClass}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Requested by email"
              />
            </Field>
          </div>
          <Button onClick={add} disabled={busy || !phone.trim()}>
            {busy ? "Adding\u2026" : "Add"}
          </Button>
        </div>
        {addError && (
          <div className="px-5 pb-4">
            <ErrorNote message={addError} />
          </div>
        )}
      </Card>

      {error && <ErrorNote message={error} />}

      <Card>
        <CardHeader title="Suppressed numbers" subtitle={`${data?.length ?? 0} entries`} />
        {loading ? (
          <p className="px-5 py-8 text-center text-sm text-ink-muted">Loading\u2026</p>
        ) : !data?.length ? (
          <EmptyState
            title="List is empty"
            hint="Numbers are added here automatically when someone asks not to be called again."
          />
        ) : (
          <ul className="divide-y divide-white/5">
            {data.map((entry) => (
              <li
                key={`${entry.phone_masked}-${entry.created_at}`}
                className="flex items-center justify-between px-5 py-3 text-sm transition-colors hover:bg-elevated/50"
              >
                <div>
                  <span className="tnum font-medium">{entry.phone_masked}</span>
                  <span className="ml-3 text-xs text-ink-muted">{entry.reason}</span>
                </div>
                <span className="text-xs text-ink-muted">
                  {formatDateTime(entry.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
