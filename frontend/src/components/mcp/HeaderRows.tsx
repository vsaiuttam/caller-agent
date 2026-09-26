/**
 * Request headers for a server, as rows of name + masked value. Values are
 * write-only: once saved, the API returns only the names.
 */

import { IconClose, IconPlus } from "../icons";
import { SecretInput, inputClass, cx } from "../ui";

export interface HeaderRow {
  id: number;
  name: string;
  value: string;
}

let nextId = 1;
export const headerRow = (name = "", value = ""): HeaderRow => ({ id: nextId++, name, value });

/** RFC 9110 token characters. */
const HEADER_NAME = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/;

/** The headers the rows describe, or the first thing wrong with them. Blank rows are ignored. */
export function headersFromRows(rows: HeaderRow[]): { headers: Record<string, string>; error: string | null } {
  const headers: Record<string, string> = {};
  const seen = new Set<string>();
  for (const row of rows) {
    const name = row.name.trim();
    const value = row.value.trim();
    if (!name && !value) continue;
    if (!name) return { headers, error: "Give every header value a name." };
    if (!HEADER_NAME.test(name)) return { headers, error: `“${name}” isn't a valid header name — letters, digits and dashes only.` };
    if (!value) return { headers, error: `Add a value for ${name}, or remove the row.` };
    if (seen.has(name.toLowerCase())) return { headers, error: `${name} is listed twice.` };
    seen.add(name.toLowerCase());
    headers[name] = value;
  }
  return { headers, error: null };
}

export function HeaderRows({
  rows,
  onChange,
  disabled = false,
}: {
  rows: HeaderRow[];
  onChange: (rows: HeaderRow[]) => void;
  disabled?: boolean;
}) {
  const update = (id: number, patch: Partial<HeaderRow>) =>
    onChange(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));

  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        // On a phone each row wraps to two lines, so it gets a frame to stay one unit.
        <div
          key={row.id}
          className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-2 sm:flex-nowrap sm:border-0 sm:p-0"
        >
          <input
            value={row.name}
            onChange={(e) => update(row.id, { name: e.target.value })}
            placeholder="Authorization"
            aria-label={`Header ${index + 1} name`}
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            className={cx(inputClass, "h-9 w-full font-mono text-[0.8125rem] sm:w-2/5")}
          />
          <SecretInput
            value={row.value}
            onChange={(e) => update(row.id, { value: e.target.value })}
            placeholder="Bearer sk-…"
            aria-label={`${row.name.trim() || `Header ${index + 1}`} value`}
            disabled={disabled}
            className="min-w-0 flex-1"
          />
          <button
            type="button"
            onClick={() => onChange(rows.filter((r) => r.id !== row.id))}
            disabled={disabled}
            aria-label={`Remove ${row.name.trim() || "header"}`}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-critical/10 hover:text-critical disabled:opacity-50"
          >
            <IconClose size={14} />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...rows, headerRow()])}
        disabled={disabled}
        className="flex h-9 w-full items-center gap-1.5 rounded-md border border-dashed border-line-strong px-3 text-left text-xs font-medium text-ink-secondary transition-colors hover:border-brand hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
      >
        <IconPlus size={14} /> Add header
      </button>
    </div>
  );
}
