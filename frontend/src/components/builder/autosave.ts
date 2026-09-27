/**
 * Never lose a campaign in progress: the builder's draft is mirrored to
 * localStorage (one key per campaign id, or `new`), debounced, and offered
 * back on return. Storage can be blocked or full; every access is guarded
 * and the builder works without it.
 */

import type { Draft, StepId } from "./draft";

const PREFIX = "samvaad.builder.";
/** Contact lists beyond this aren't autosaved; the file is quick to re-drop. */
const MAX_CONTACTS = 2000;

export interface Saved {
  v: 1;
  savedAt: number;
  step: StepId;
  draft: Draft;
  /** The contacts were too many to keep, so they were left out. */
  contactsDropped?: number;
}

export const autosaveKey = (id: string | null) => `${PREFIX}${id ?? "new"}`;

export function readAutosave(key: string): Saved | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Saved;
    return parsed?.v === 1 && parsed.draft?.form ? parsed : null;
  } catch {
    return null;
  }
}

export function writeAutosave(key: string, draft: Draft, step: StepId): void {
  const tooMany = draft.contacts.length > MAX_CONTACTS;
  const value: Saved = {
    v: 1,
    savedAt: Date.now(),
    step,
    draft: tooMany ? { ...draft, contacts: [], rejected: [] } : draft,
    ...(tooMany ? { contactsDropped: draft.contacts.length } : {}),
  };
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota or private mode: try once more without the contacts.
    try {
      localStorage.setItem(key, JSON.stringify({ ...value, draft: { ...value.draft, contacts: [], rejected: [] }, contactsDropped: draft.contacts.length }));
    } catch {
      /* nothing more to do */
    }
  }
}

export function clearAutosave(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* blocked storage */
  }
}
