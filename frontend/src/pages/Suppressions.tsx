import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { IconBlock, IconPlus, IconSearch } from "../components/icons";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Field,
  Input,
  Page,
  PageHeader,
  Skeleton,
  toast,
} from "../components/ui";
import { formatDateTime } from "../format";
import { useAsync, useDocumentTitle } from "../hooks";

const E164 = /^\+[1-9]\d{6,14}$/;

export default function Suppressions() {
  useDocumentTitle("Do not call");
  const { data, loading, error, reload } = useAsync(() => api.suppressions());
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const [query, setQuery] = useState("");

  const number = phone.replace(/[\s\-().]/g, "");
  const valid = E164.test(number);

  const add = async (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!valid) return;
    setBusy(true);
    try {
      await api.addSuppression(number, reason.trim() || "Manually added");
      toast.success("Number blocked", "It will never be dialled, in any campaign.");
      setPhone("");
      setReason("");
      setTouched(false);
      reload();
    } catch (err) {
      toast.error("Couldn't add the number", (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter((e) => !q || e.phone_masked.includes(q) || e.reason.toLowerCase().includes(q));
  }, [data, query]);

  return (
    <Page width="narrow">
      <PageHeader
        icon={<IconBlock size={18} />}
        title="Do not call"
        description="Numbers here are never dialled, across every campaign. People who ask not to be called again are added automatically."
      />

      <Card className="mb-4">
        <CardHeader title="Block a number" />
        <form onSubmit={add} className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] sm:items-start">
          <Field label="Phone number" error={touched && phone && !valid ? "Use + and the country code." : null} hint={!touched || valid ? "e.g. +14155550123" : undefined}>
            <Input
              type="tel"
              className="tnum"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onBlur={() => setTouched(true)}
              aria-invalid={touched && !!phone && !valid}
              placeholder="+14155550123"
            />
          </Field>
          <Field label="Reason" optional>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Requested by email" />
          </Field>
          <Button type="submit" loading={busy} disabled={!phone.trim()} icon={<IconPlus size={14} />} className="sm:mt-[22px]">
            Block
          </Button>
        </form>
      </Card>

      {error && (
        <div className="mb-4">
          <ErrorNote message={error} onRetry={reload} />
        </div>
      )}

      <Card className="overflow-hidden">
        <CardHeader
          title="Blocked numbers"
          subtitle={loading ? "Loading…" : `${data?.length ?? 0} ${data?.length === 1 ? "number" : "numbers"}`}
          action={
            (data?.length ?? 0) > 8 && (
              <label className="relative w-44">
                <span className="sr-only">Search blocked numbers</span>
                <IconSearch size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted" />
                <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search" className="h-8 pl-8 text-xs" />
              </label>
            )
          }
        />
        {loading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : !data?.length ? (
          <EmptyState
            compact
            avatar="ended"
            title="Nobody has opted out yet"
            hint="When someone asks not to be called again, the agent adds them here automatically."
          />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Number</th>
                <th>Reason</th>
                <th className="text-right">Added</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((entry) => (
                <tr key={`${entry.phone_masked}-${entry.created_at}`}>
                  <td className="tnum font-medium text-ink">{entry.phone_masked}</td>
                  <td className="text-ink-secondary">{entry.reason}</td>
                  <td className="whitespace-nowrap text-right text-xs text-ink-muted">{formatDateTime(entry.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </Page>
  );
}
