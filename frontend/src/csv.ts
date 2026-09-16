/**
 * CSV → contact rows.
 *
 * Handles quoted fields and embedded commas, which is where a naive
 * `split(",")` breaks on real spreadsheet exports — a name like
 * `"Whitfield, Dana"` would otherwise shift every subsequent column.
 */

import type { NewContact } from "./api";

export interface ParseResult {
  contacts: NewContact[];
  /** Rows dropped, with the reason, so the UI can explain rather than silently lose data. */
  rejected: Array<{ line: number; reason: string }>;
  /** Column headers that became per-contact context for the agent. */
  attributeColumns: string[];
}

export function parseContactsCsv(text: string): ParseResult {
  const rows = splitRows(text);
  if (rows.length < 2) {
    return { contacts: [], rejected: [], attributeColumns: [] };
  }

  const headers = rows[0].map((h) => h.trim().toLowerCase());
  const find = (...names: string[]) => headers.findIndex((h) => names.includes(h));

  const nameAt = find("name", "full_name", "fullname", "contact", "customer");
  const phoneAt = find("phone", "phone_e164", "number", "mobile", "telephone");
  const tzAt = find("timezone", "tz", "time_zone");

  if (nameAt < 0 || phoneAt < 0) {
    return {
      contacts: [],
      rejected: [{ line: 1, reason: "Missing a 'name' or 'phone' column" }],
      attributeColumns: [],
    };
  }

  const attributeColumns = headers.filter(
    (_, i) => i !== nameAt && i !== phoneAt && i !== tzAt,
  );

  const contacts: NewContact[] = [];
  const rejected: ParseResult["rejected"] = [];

  rows.slice(1).forEach((cells, i) => {
    const line = i + 2; // 1-indexed, +1 for the header row
    const name = (cells[nameAt] ?? "").trim();
    const phone = normalisePhone(cells[phoneAt] ?? "");

    if (!name) {
      rejected.push({ line, reason: "No name" });
      return;
    }
    if (!phone) {
      rejected.push({
        line,
        reason: `Unrecognised phone number: ${(cells[phoneAt] ?? "").trim() || "(empty)"}`,
      });
      return;
    }

    const attributes: Record<string, string> = {};
    headers.forEach((header, col) => {
      if (col === nameAt || col === phoneAt || col === tzAt) return;
      const value = (cells[col] ?? "").trim();
      if (value) attributes[header] = value;
    });

    contacts.push({
      full_name: name,
      phone_e164: phone,
      timezone: (cells[tzAt] ?? "").trim() || "America/New_York",
      attributes,
    });
  });

  return { contacts, rejected, attributeColumns };
}

function splitRows(text: string): string[][] {
  const rows: string[][] = [];
  let cells: string[] = [];
  let cell = "";
  let quoted = false;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];

    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"'; // escaped quote
          i++;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }

    if (ch === '"') quoted = true;
    else if (ch === ",") {
      cells.push(cell);
      cell = "";
    } else if (ch === "\n") {
      cells.push(cell.replace(/\r$/, ""));
      if (cells.some((c) => c.trim())) rows.push(cells);
      cells = [];
      cell = "";
    } else cell += ch;
  }

  cells.push(cell);
  if (cells.some((c) => c.trim())) rows.push(cells);
  return rows;
}

/** Coerce common spreadsheet formats to E.164; return null for anything unusable. */
export function normalisePhone(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  const digits = trimmed.replace(/[^\d+]/g, "");
  if (digits.startsWith("+")) {
    return /^\+[1-9]\d{6,14}$/.test(digits) ? digits : null;
  }
  // Bare 10-digit numbers are overwhelmingly US/Canada in these exports.
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  return null;
}
