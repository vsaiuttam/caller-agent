/**
 * Turn a tool's `input_schema` into form fields, and form drafts back into
 * arguments.
 *
 * Strings, numbers, integers, booleans and enums become real fields.
 * Anything else — nested objects, arrays, $refs, unions — becomes a JSON
 * field of its own, and a schema that isn't a plain object of properties
 * falls back to editing the whole arguments object as JSON. Nothing a tool
 * accepts is ever unreachable from the form.
 */

import type { JsonSchema, JsonValue } from "../../api";
import { formatJson } from "../../format";
import { toolTitle } from "./toolText";

export type FieldKind = "string" | "text" | "date" | "number" | "integer" | "boolean" | "enum" | "json";

export interface SchemaField {
  key: string;
  label: string;
  description: string;
  required: boolean;
  kind: FieldKind;
  /** The property's schema with any `Optional[...]` wrapper removed. */
  schema: JsonSchema;
  /** Enum choices, in schema order. */
  options: JsonValue[];
  placeholder: string;
}

export type FormPlan =
  | { mode: "none" }
  | { mode: "form"; fields: SchemaField[] }
  | { mode: "json"; reason: string };

/** A field's in-progress value: text for inputs, a flag for switches. */
export type Draft = Record<string, string | boolean>;
export type Arguments = Record<string, JsonValue>;

const PRIMITIVE = new Set(["string", "number", "boolean"]);
const LONG_TEXT = /(body|content|description|message|notes?|summary|text)$/i;

/** `Optional[str]` arrives as anyOf [{type: string}, {type: null}]: keep the real branch. */
function unwrap(schema: JsonSchema): JsonSchema {
  const branches = schema.anyOf ?? schema.oneOf;
  if (branches) {
    const real = branches.filter((b) => b.type !== "null");
    if (real.length !== 1) return schema;
    return {
      ...real[0],
      title: schema.title ?? real[0].title,
      description: schema.description ?? real[0].description,
      default: schema.default ?? real[0].default,
    };
  }
  if (Array.isArray(schema.type)) {
    const real = schema.type.filter((t) => t !== "null");
    if (real.length === 1) return { ...schema, type: real[0] };
  }
  return schema;
}

function kindOf(key: string, schema: JsonSchema): FieldKind {
  if (schema.enum?.length && schema.enum.every((v) => v === null || PRIMITIVE.has(typeof v))) return "enum";
  switch (schema.type) {
    case "string":
      if (schema.format === "date") return "date";
      return (schema.maxLength ?? 0) > 200 || LONG_TEXT.test(key) ? "text" : "string";
    case "number":
      return "number";
    case "integer":
      return "integer";
    case "boolean":
      return "boolean";
    default:
      return "json";
  }
}

function placeholderFor(kind: FieldKind, schema: JsonSchema): string {
  const example = schema.examples?.[0] ?? schema.default;
  if (example !== undefined && example !== null && kind !== "json") return String(example);
  if (kind === "json") return schema.type === "array" ? "[]" : "{}";
  if (schema.format === "date-time") return "2026-01-31T15:00:00";
  if (schema.format === "email") return "name@example.com";
  return "";
}

export function planForm(schema: JsonSchema | null | undefined): FormPlan {
  const root = unwrap(schema ?? {});
  if (root.$ref || root.allOf || root.anyOf || root.oneOf || (root.type !== undefined && root.type !== "object")) {
    return { mode: "json", reason: "This tool's inputs are too intricate for a form — edit the arguments as JSON." };
  }
  const properties = root.properties ?? {};
  const keys = Object.keys(properties);
  if (!keys.length) {
    const open = root.additionalProperties === true || typeof root.additionalProperties === "object";
    return open ? { mode: "json", reason: "This tool takes free-form arguments — write them as JSON." } : { mode: "none" };
  }
  const required = new Set(root.required ?? []);
  return {
    mode: "form",
    fields: keys.map((key) => {
      const property = unwrap(properties[key]);
      const kind = kindOf(key, property);
      return {
        key,
        label: property.title ?? toolTitle(key),
        description: property.description ?? "",
        required: required.has(key),
        kind,
        schema: property,
        options: kind === "enum" ? (property.enum ?? []) : [],
        placeholder: placeholderFor(kind, property),
      };
    }),
  };
}

function toDraft(field: SchemaField, value: JsonValue | undefined): string | boolean {
  if (field.kind === "boolean") return value === true;
  if (value === undefined || value === null) return "";
  if (field.kind === "enum") {
    const index = field.options.findIndex((option) => option === value);
    return index >= 0 ? String(index) : "";
  }
  if (field.kind === "json") return formatJson(value);
  return typeof value === "string" ? value : String(value);
}

/** Defaults filled in, everything else empty. */
export function initialDraft(fields: SchemaField[]): Draft {
  return Object.fromEntries(fields.map((f) => [f.key, toDraft(f, f.schema.default)]));
}

/** Load arguments written as JSON back into the form. */
export function draftFromArgs(fields: SchemaField[], args: Arguments): Draft {
  return Object.fromEntries(fields.map((f) => [f.key, toDraft(f, args[f.key] ?? f.schema.default)]));
}

/**
 * The arguments a draft describes, and what's wrong with it. Empty optional
 * fields are left out rather than sent as "" — a tool treats a missing
 * argument as "use your default", and "" as a real value.
 */
export function buildArgs(
  fields: SchemaField[],
  draft: Draft,
  touched: ReadonlySet<string>,
): { args: Arguments; errors: Record<string, string> } {
  const args: Arguments = {};
  const errors: Record<string, string> = {};

  for (const field of fields) {
    const raw = draft[field.key];
    if (field.kind === "boolean") {
      if (field.required || touched.has(field.key) || field.schema.default !== undefined) args[field.key] = raw === true;
      continue;
    }
    const text = typeof raw === "string" ? raw : "";
    if (!text.trim()) {
      if (field.required) errors[field.key] = field.kind === "enum" ? "Choose one." : "Required.";
      continue;
    }
    switch (field.kind) {
      case "enum":
        args[field.key] = field.options[Number(text)] ?? null;
        break;
      case "number":
      case "integer": {
        const n = Number(text);
        const { minimum, maximum } = field.schema;
        if (!Number.isFinite(n)) errors[field.key] = "Enter a number.";
        else if (field.kind === "integer" && !Number.isInteger(n)) errors[field.key] = "Enter a whole number.";
        else if (minimum !== undefined && n < minimum) errors[field.key] = `At least ${minimum}.`;
        else if (maximum !== undefined && n > maximum) errors[field.key] = `At most ${maximum}.`;
        else args[field.key] = n;
        break;
      }
      case "json":
        try {
          args[field.key] = JSON.parse(text) as JsonValue;
        } catch {
          errors[field.key] = "Not valid JSON.";
        }
        break;
      default:
        args[field.key] = text;
    }
  }
  return { args, errors };
}

/** Parse the JSON editor: it must hold an object. */
export function parseArgs(text: string): { args: Arguments } | { error: string } {
  if (!text.trim()) return { args: {} };
  try {
    const value = JSON.parse(text) as JsonValue;
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      return { error: "Arguments must be a JSON object — { \"name\": value, … }." };
    }
    return { args: value };
  } catch (err) {
    return { error: `Not valid JSON: ${(err as Error).message}` };
  }
}
