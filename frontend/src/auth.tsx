/**
 * Access control, the frontend half of §1.6 and the accounts round.
 *
 * On load we ask /api/auth/status. Three outcomes:
 *   - auth off (no ADMIN_PASSWORD and no accounts yet, or an older backend
 *     without the endpoint): the console opens as before, with a dismissible
 *     banner saying anyone with the link can dial;
 *   - auth on and our token is good: the console opens, with the signed-in
 *     user (name, email, role) in the account menu;
 *   - auth on and no good token: `/app/*` redirects to `/login?next=…`.
 * Any 401 later (or a socket closed with 4401) flips the phase to "locked",
 * which sends the console back to the login page the same way.
 *
 * `registration` says how new people get in (owner bootstrap, invite, open,
 * closed). It is null on backends from before accounts, which is how the
 * login page knows to offer only the shared admin password.
 *
 * The marketing page and the login page are public and never wait on this.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  api,
  type AuthStatus,
  type AuthUser,
  type Credentials,
  type RegisterRequest,
  type RegistrationInfo,
} from "./api";
import { getToken, onUnauthorized, setSession } from "./authStore";
import { LOGIN } from "./routes";

export type AuthPhase =
  /** Asking the server. */
  | "checking"
  /** Auth is off — everything is open. */
  | "open"
  /** Auth is on and we're signed in. */
  | "signed-in"
  /** Auth is on and we need to sign in. */
  | "locked"
  /** The status check failed (server down). Let the app render its own errors. */
  | "unknown";

interface AuthContextValue {
  phase: AuthPhase;
  enabled: boolean;
  /** Who is signed in. Null when auth is off, or on a backend without accounts. */
  user: AuthUser | null;
  /** Null on a backend from before accounts. */
  registration: RegistrationInfo | null;
  /**
   * Why we are locked: "signed-out" (you pressed Sign out), "expired" (a
   * request came back 401 mid-session), or null (never signed in here).
   */
  lockReason: "signed-out" | "expired" | null;
  /**
   * Throws ApiError on wrong credentials (401), a disabled account (403) or a
   * lockout (429). `onAccepted` runs as soon as the server says yes, and the
   * app opens `holdMs` later — time for the agent to wave you in.
   */
  signIn: (credentials: Credentials, onAccepted?: () => void, holdMs?: number) => Promise<void>;
  /** Create an account and sign in with it. Throws ApiError (400/403/409/429). */
  register: (body: RegisterRequest, onAccepted?: () => void, holdMs?: number) => Promise<void>;
  /** Forget the token. Prefer useSignOut(), which also goes to /login. */
  signOut: () => void;
  /** Ask the server again (the login page's Retry). */
  recheck: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  phase: "unknown",
  enabled: false,
  user: null,
  registration: null,
  lockReason: null,
  signIn: async () => {},
  register: async () => {},
  signOut: () => {},
  recheck: () => {},
});

const wait = (ms: number) => (ms > 0 ? new Promise((resolve) => window.setTimeout(resolve, ms)) : Promise.resolve());

export function AuthProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<AuthPhase>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [registration, setRegistration] = useState<RegistrationInfo | null>(null);
  const [lockReason, setLockReason] = useState<AuthContextValue["lockReason"]>(null);
  const [attempt, setAttempt] = useState(0);

  const apply = useCallback((status: AuthStatus) => {
    setRegistration(status.registration ?? null);
    if (!status.auth_enabled) {
      setUser(null);
      setPhase("open");
    } else if (status.authenticated && getToken()) {
      setUser(status.user ?? null);
      setPhase("signed-in");
    } else {
      setSession(null);
      setUser(null);
      setPhase("locked");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (attempt > 0) setPhase("checking");
    api
      .authStatus()
      .then((status) => {
        if (!cancelled) apply(status);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // No such endpoint: a backend from before auth existed. It's open.
        setPhase(err instanceof ApiError && err.status === 404 ? "open" : "unknown");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt, apply]);

  useEffect(
    () =>
      onUnauthorized(() => {
        setUser(null);
        setLockReason((r) => r ?? "expired");
        setPhase("locked");
      }),
    [],
  );

  const recheck = useCallback(() => setAttempt((n) => n + 1), []);

  /** After a new session: learn who we are (older login responses don't say). */
  const adopt = useCallback(async (fallback: AuthUser | null) => {
    try {
      const status = await api.authStatus();
      setRegistration(status.registration ?? null);
      setUser(status.user ?? fallback);
    } catch {
      setUser(fallback);
    }
  }, []);

  const signIn = useCallback(
    async (credentials: Credentials, onAccepted?: () => void, holdMs = 0) => {
      const result = await api.login(credentials);
      setSession({ token: result.token, expires_at: result.expires_at });
      onAccepted?.();
      await Promise.all([adopt(result.user ?? null), wait(holdMs)]);
      setLockReason(null);
      setPhase("signed-in");
    },
    [adopt],
  );

  const register = useCallback(
    async (body: RegisterRequest, onAccepted?: () => void, holdMs = 0) => {
      const result = await api.register(body);
      setSession({ token: result.token, expires_at: result.expires_at });
      onAccepted?.();
      await Promise.all([adopt(result.user ?? null), wait(holdMs)]);
      setLockReason(null);
      setPhase("signed-in");
    },
    [adopt],
  );

  const signOut = useCallback(() => {
    // Reason first: setSession(null) notifies listeners synchronously.
    setLockReason("signed-out");
    setSession(null);
    setUser(null);
    setPhase("locked");
  }, []);

  return (
    <AuthContext.Provider
      value={{
        phase,
        enabled: phase === "signed-in" || phase === "locked",
        user,
        registration,
        lockReason,
        signIn,
        register,
        signOut,
        recheck,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

/**
 * Sign out and land on the login page (plain `/login`, no `next`). The
 * console's guard also sends a signed-out visitor to plain `/login`, so it
 * doesn't matter which of the two updates React renders first.
 */
export function useSignOut() {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  return useCallback(() => {
    signOut();
    navigate(LOGIN, { replace: true });
  }, [signOut, navigate]);
}

/** Owners and admins manage the team. */
export function canManageTeam(user: AuthUser | null): boolean {
  return user?.role === "owner" || user?.role === "admin";
}

export const ROLE_LABEL: Record<AuthUser["role"], string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};
