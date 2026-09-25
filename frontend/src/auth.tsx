/**
 * Access control, the frontend half of §1.6.
 *
 * On load we ask /api/auth/status. Three outcomes:
 *   - auth off (or an older backend without the endpoint): the app opens as
 *     before, with a dismissible banner saying anyone with the link can dial;
 *   - auth on and our token is good: the app opens, with Sign out;
 *   - auth on and no good token: the login page.
 * Any 401 later (or a socket closed with 4401) drops back to the login page.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, api } from "./api";
import { getToken, onUnauthorized, setSession } from "./authStore";

export type AuthPhase =
  /** Asking the server. */
  | "checking"
  /** Auth is off — everything is open. */
  | "open"
  /** Auth is on and we're signed in. */
  | "signed-in"
  /** Auth is on and we need a password. */
  | "locked"
  /** The status check failed (server down). Let the app render its own errors. */
  | "unknown";

interface AuthContextValue {
  phase: AuthPhase;
  enabled: boolean;
  /**
   * Throws ApiError on a wrong password (401) or lockout (429). `onAccepted`
   * runs as soon as the server says yes, and the app opens `holdMs` later —
   * time for the login page's agent to wave you in.
   */
  signIn: (password: string, onAccepted?: () => void, holdMs?: number) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  phase: "unknown",
  enabled: false,
  signIn: async () => {},
  signOut: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<AuthPhase>("checking");

  useEffect(() => {
    let cancelled = false;
    api
      .authStatus()
      .then((status) => {
        if (cancelled) return;
        if (!status.auth_enabled) setPhase("open");
        else if (status.authenticated && getToken()) setPhase("signed-in");
        else {
          setSession(null);
          setPhase("locked");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // No such endpoint: a backend from before auth existed. It's open.
        setPhase(err instanceof ApiError && err.status === 404 ? "open" : "unknown");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => onUnauthorized(() => setPhase("locked")), []);

  const signIn = useCallback(async (password: string, onAccepted?: () => void, holdMs = 0) => {
    const result = await api.login(password);
    setSession(result);
    onAccepted?.();
    if (holdMs > 0) await new Promise((resolve) => window.setTimeout(resolve, holdMs));
    setPhase("signed-in");
  }, []);

  const signOut = useCallback(() => {
    setSession(null);
    setPhase("locked");
  }, []);

  return (
    <AuthContext.Provider
      value={{ phase, enabled: phase === "signed-in" || phase === "locked", signIn, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
