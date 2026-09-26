/**
 * Where things live. The marketing page is `/`, sign-in is `/login`, and the
 * console is everything under `/app`. v1 put the console at the root
 * (`/dashboard`, `/calls?call=…`); App.tsx redirects those here, keeping the
 * query string and hash, so old bookmarks and shared links still land.
 */

import type { Location } from "react-router-dom";

export const APP = "/app";
export const LOGIN = "/login";

/** The console's overview (the v1 `/dashboard`). */
export const OVERVIEW = APP;

/** v1 top-level console paths that now live under `/app`. */
export const LEGACY_SECTIONS = [
  "campaigns",
  "calls",
  "review",
  "live",
  "test-lab",
  "templates",
  "models",
  "settings",
  "suppressions",
] as const;

/**
 * Where to go after signing in. Only console paths are accepted, so a crafted
 * `?next=https://evil.example` or `?next=//evil.example` can't turn the login
 * page into an open redirect.
 */
export function safeNext(raw: string | null | undefined): string {
  if (!raw) return OVERVIEW;
  let path = raw;
  try {
    // Resolve against our own origin, then insist it stayed there.
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin) return OVERVIEW;
    path = `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return OVERVIEW;
  }
  return path === APP || path.startsWith(`${APP}/`) || path.startsWith(`${APP}?`) || path.startsWith(`${APP}#`)
    ? path
    : OVERVIEW;
}

/** `/login`, remembering the console page that sent us there. */
export function loginFor(location: Pick<Location, "pathname" | "search" | "hash">): string {
  const next = `${location.pathname}${location.search}${location.hash}`;
  return next === APP || next === `${APP}/` ? LOGIN : `${LOGIN}?next=${encodeURIComponent(next)}`;
}
