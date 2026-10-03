import { useState, type DragEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { IconPlus, IconUpload, IconUsers } from "../icons";
import { PhoneInput, countryOf, isValidPhone } from "../PhoneInput";
import { Button, Callout, Card, CardHeader, ConfirmDialog, Field, Input, Textarea, cx, toast } from "../ui";
import { useBuilder } from "./context";

export function ContactsStep() {
  const { draft, update, mode, campaign } = useBuilder();
  const [pasted, setPasted] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const saved = campaign?.total_contacts ?? 0;

  const ingest = async (file: File) => {
    setParsing(true);
    setParseError(null);
    try {
      const result = await api.parseContactsFile(file, draft.form.language);
      update({ contacts: result.contacts, rejected: result.rejected, attributeColumns: result.attribute_columns });
      if (result.contacts.length) toast.success(`${result.contacts.length} contacts ready`, "They're imported when you save or launch.");
    } catch (err) {
      setParseError((err as Error).message);
    } finally {
      setParsing(false);
    }
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void ingest(file);
  };

  const clear = () => {
    update({ contacts: [], rejected: [], attributeColumns: [] });
    setPasted("");
    setConfirmClear(false);
  };

  const preview = draft.contacts.slice(0, 50);
  const extra = draft.attributeColumns.slice(0, 3);

  return (
    <Card>
      <CardHeader
        title="Contacts"
        subtitle="Excel or CSV with name and phone columns. Extra columns become context the agent can use. Numbers on the do-not-call list are skipped."
      />
      <div className="space-y-4 px-5 py-5">
        {mode === "edit" && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-subtle/50 px-4 py-3 text-sm">
            <span className="flex items-center gap-2 text-ink-secondary">
              <IconUsers size={15} />
              <span>
                <span className="tnum font-semibold text-ink">{saved.toLocaleString()}</span> already on this campaign
              </span>
            </span>
            {campaign && (
              <Link to={`/app/campaigns/${campaign.id}?tab=contacts`} className="text-xs font-medium text-brand hover:underline">
                View them
              </Link>
            )}
          </div>
        )}

        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            "flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 text-center transition-colors",
            dragging ? "border-brand bg-brand/6" : "border-line-strong hover:border-brand/60 hover:bg-subtle/60",
            parsing && "pointer-events-none opacity-60",
          )}
        >
          <input
            type="file"
            accept=".csv,.xlsx,.xls,.xlsm,text/csv"
            className="sr-only"
            disabled={parsing}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void ingest(file);
              e.target.value = "";
            }}
          />
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-subtle text-ink-secondary">
            <IconUpload size={18} />
          </span>
          <span className="text-sm font-medium text-ink">
            {parsing ? "Reading…" : mode === "edit" ? "Drop more contacts here, or choose a file" : "Drop a file here, or choose one"}
          </span>
          <span className="text-2xs text-ink-muted">.xlsx · .xls · .csv</span>
        </label>

        <AddContact />

        <details className="group" open={!!pasted}>
          <summary className="cursor-pointer rounded text-xs font-medium text-ink-muted transition-colors hover:text-ink">Or paste rows</summary>
          <Textarea
            className="mt-2 min-h-24 font-mono text-xs"
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            placeholder={"name,phone,city\nAnanya Rao,+919812345678,Pune"}
            aria-label="Paste contact rows"
          />
          <Button
            size="sm"
            variant="secondary"
            className="mt-2"
            disabled={!pasted.trim()}
            loading={parsing}
            onClick={() => void ingest(new File([pasted], "pasted.csv", { type: "text/csv" }))}
          >
            Read pasted rows
          </Button>
        </details>

        {parseError && <Callout tone="critical">{parseError}</Callout>}

        {draft.contacts.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-line">
            <div className="flex items-center justify-between border-b border-line bg-subtle/50 px-3 py-2">
              <span className="text-xs font-medium text-ink">
                {draft.contacts.length.toLocaleString()} new contact{draft.contacts.length === 1 ? "" : "s"} ready
                {mode === "edit" ? " to add" : ""}
              </span>
              <button type="button" onClick={() => setConfirmClear(true)} className="text-xs font-medium text-ink-muted transition-colors hover:text-critical">
                Clear
              </button>
            </div>
            <div className="max-h-72 overflow-auto">
              <table className="data-table min-w-[420px]" data-density="compact">
                <thead className="sticky top-0 bg-surface">
                  <tr>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Timezone</th>
                    {extra.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.map((c, i) => (
                    <tr key={`${c.phone_e164}-${i}`}>
                      <td className="font-medium text-ink">{c.full_name}</td>
                      <td className="tnum whitespace-nowrap text-ink-muted">{c.phone_e164}</td>
                      <td className="whitespace-nowrap text-xs text-ink-muted">{c.timezone}</td>
                      {extra.map((col) => (
                        <td key={col} className="max-w-40 truncate text-xs text-ink-secondary">
                          {c.attributes?.[col] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {draft.contacts.length > 50 && (
              <p className="border-t border-line px-3 py-1.5 text-xs text-ink-muted">Showing 50 of {draft.contacts.length.toLocaleString()}.</p>
            )}
            {draft.attributeColumns.length > 0 && (
              <p className="border-t border-line px-3 py-2 text-xs text-ink-muted">
                Extra context per contact: <span className="text-ink-secondary">{draft.attributeColumns.join(", ")}</span>
              </p>
            )}
          </div>
        )}

        {draft.rejected.length > 0 && (
          <Callout tone="warning" title={`${draft.rejected.length} row${draft.rejected.length === 1 ? "" : "s"} skipped`}>
            {draft.rejected.slice(0, 5).map((r) => (
              <span key={r.line} className="block">
                Line {r.line}: {r.reason}
              </span>
            ))}
            {draft.rejected.length > 5 && <span className="block">…and {draft.rejected.length - 5} more.</span>}
          </Callout>
        )}
      </div>

      <ConfirmDialog
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        onConfirm={clear}
        title="Clear these contacts?"
        description={`The ${draft.contacts.length.toLocaleString()} contacts you loaded here go. Nothing saved on the server changes.`}
        confirmLabel="Clear contacts"
      />
    </Card>
  );
}

/** One contact typed in by hand: a name, a country and a local number. */
function AddContact() {
  const { draft, update } = useBuilder();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [touched, setTouched] = useState(false);
  const valid = isValidPhone(phone);
  const duplicate = valid && draft.contacts.some((c) => c.phone_e164 === phone);
  const error = !touched || !phone ? null : !valid ? "That number looks too short or too long for this country." : duplicate ? "That number is already in the list." : null;

  const add = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!name.trim() || !valid || duplicate) return;
    const timezone = countryOf(phone)?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
    update({ contacts: [...draft.contacts, { full_name: name.trim(), phone_e164: phone, timezone, attributes: {} }] });
    toast.success(`${name.trim()} added`, "Imported when you save or launch.");
    setName("");
    setPhone("");
    setTouched(false);
  };

  return (
    <form onSubmit={add} className="rounded-xl border border-line bg-subtle/40 p-4">
      <p className="mb-3 text-xs font-medium text-ink-secondary">Add a contact</p>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto] sm:items-start">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ananya Rao" autoComplete="off" />
        </Field>
        <Field label="Phone number" group error={error}>
          <PhoneInput value={phone} onChange={setPhone} onBlur={() => setTouched(true)} invalid={!!error} />
        </Field>
        <Button type="submit" variant="secondary" icon={<IconPlus size={14} />} disabled={!name.trim() || !phone} className="sm:mt-[22px]">
          Add
        </Button>
      </div>
    </form>
  );
}
