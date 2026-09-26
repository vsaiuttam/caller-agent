/**
 * Tool names are identifiers (`check_availability`, `lookupCustomer`,
 * `gmail_send_email`). These turn them into words: a title for lists, and an
 * activity line for the live transcript ("Checking availability…").
 */

/** Leading words we know are verbs, so "Checking …" is safe to say. */
const VERBS = new Set([
  "add", "assign", "attach", "book", "calculate", "call", "cancel", "check", "close", "comment",
  "compute", "confirm", "count", "create", "delete", "draft", "edit", "fetch", "find", "generate",
  "get", "insert", "list", "load", "log", "look", "make", "mark", "move", "notify", "open", "patch",
  "post", "put", "query", "read", "record", "remove", "reply", "reschedule", "retrieve", "run",
  "save", "schedule", "search", "send", "set", "start", "stop", "submit", "sync", "tag", "update",
  "upsert", "validate", "verify", "write",
]);

/** Verbs whose final consonant doubles: get → getting, cancel → cancelling. */
const DOUBLED = new Set(["cancel", "get", "log", "put", "run", "set", "stop", "tag"]);

/** Compound verbs written as one word. */
const PHRASAL: Record<string, [string, string]> = {
  lookup: ["look", "up"],
  checkin: ["check", "in"],
  checkout: ["check", "out"],
  setup: ["set", "up"],
  signup: ["sign", "up"],
};

function words(name: string): string[] {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[\s_\-.]+/)
    .filter(Boolean)
    .map((w) => w.toLowerCase());
}

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function gerund(verb: string): string {
  if (DOUBLED.has(verb)) return `${verb}${verb.slice(-1)}ing`;
  if (verb.endsWith("ie")) return `${verb.slice(0, -2)}ying`;
  if (verb.endsWith("e") && !verb.endsWith("ee") && verb.length > 2) return `${verb.slice(0, -1)}ing`;
  return `${verb}ing`;
}

/** "check_availability" → "Check availability". */
export function toolTitle(name: string): string {
  return capitalise(words(name).join(" ")) || name;
}

/**
 * "check_availability" → "Checking availability"; "gmail_send_email" →
 * "Sending email". Names without a verb we recognise read "Using …".
 */
export function toolActivity(name: string): string {
  const parts = words(name);
  const at = parts.findIndex((w) => VERBS.has(w) || w in PHRASAL);
  if (at < 0) return `Using ${toolTitle(name).toLowerCase()}`;
  const [verb, particle] = PHRASAL[parts[at]] ?? [parts[at], ""];
  const rest = [particle, ...parts.slice(at + 1)].filter(Boolean).join(" ");
  return capitalise(rest ? `${gerund(verb)} ${rest}` : gerund(verb));
}

/** Tool ids are `{server_slug}__{name}`; the name is the part that reads well. */
export function toolNameFromId(id: string): string {
  const cut = id.indexOf("__");
  return cut >= 0 ? id.slice(cut + 2) : id;
}
