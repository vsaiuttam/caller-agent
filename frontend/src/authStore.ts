/**
 * The session token, outside React so the API client and the event socket
 * can read it without a provider.
 *
 * Auth is opt-in on the backend (ADMIN_PASSWORD). With it off there is never
 * a token and every helper here is a no-op — requests go out exactly as
 * before. With it on:
 *   - HTTP sends `Authorization: Bearer <token>`,
 *   - URLs the browser fetches itself (WebSockets, <audio>, downloads) carry
 *     `?token=<token>`,
 *   - any 401 (or a socket closed with 4401) clears the token and tells the
 *     AuthProvider, which swaps the app for the login page.
 */

const KEY = "samvaad.auth";

interface Stored {
  token: string;
  /** ISO 8601. */
  expires_at: string;
}

let current: Stored | null = read();
const tokenListeners = new Set<() => void>();
const unauthorizedListeners = new Set<() => void>();

function read(): Stored | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    if (!parsed.token || new Date(parsed.expires_at).getTime() <= Date.now()) {
      localStorage.removeItem(KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  if (current && new Date(current.expires_at).getTime() <= Date.now()) {
    // Expired while the tab was open. Drop it; the next request 401s cleanly.
    setSession(null);
  }
  return current?.token ?? null;
}

export function setSession(session: Stored | null) {
  current = session;
  try {
    if (session) localStorage.setItem(KEY, JSON.stringify(session));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage blocked — the token lives for this tab only */
  }
  tokenListeners.forEach((fn) => fn());
}

export function onTokenChange(fn: () => void): () => void {
  tokenListeners.add(fn);
  return () => tokenListeners.delete(fn);
}

export function onUnauthorized(fn: () => void): () => void {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
}

export function notifyUnauthorized() {
  if (current) setSession(null);
  unauthorizedListeners.forEach((fn) => fn());
}

/** Append `token=` to a URL the browser will fetch on its own. */
export function withToken(url: string): string {
  const token = getToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
