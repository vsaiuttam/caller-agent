/**
 * Sign in, at /login. Public. What it shows depends on the server:
 *
 *   checking     a skeleton while /api/auth/status answers
 *   signed in    straight on to `next` (or the overview)
 *   open         auth is off: "Enter the console", and how to lock it
 *   unreachable  Retry, or continue to the console anyway
 *   locked       email + password (accounts), with the shared admin password
 *                as a secondary way in; only the admin password on backends
 *                from before accounts
 *
 * The agent reacts: it listens while you type, thinks while the server
 * checks, frowns at a wrong password and waves you in on success.
 */

import { useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { BRAND } from "../brand";
import type { AgentState } from "../components/AgentAvatar";
import {
  AuthField,
  AuthHeading,
  AuthLayout,
  AuthSkeleton,
  EMAIL_SHAPE,
  PasswordInput,
  authInputClass,
  useCooldown,
} from "../components/site/AuthLayout";
import { pageNameFor } from "../components/shell/nav";
import { IconArrowRight, IconLock, IconRefresh } from "../components/icons";
import { Button, Callout } from "../components/ui";
import { useDocumentTitle } from "../hooks";
import { APP, safeNext } from "../routes";

export default function Login() {
  const auth = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const next = safeNext(params.get("next"));
  const signedOut = (location.state as { signedOut?: boolean } | null)?.signedOut === true;
  const [mood, setMood] = useState<AgentState>("idle");
  useDocumentTitle("Sign in");

  if (auth.phase === "signed-in") return <Navigate to={next} replace />;

  return (
    <AuthLayout mood={auth.phase === "unknown" ? "error" : mood}>
      {auth.phase === "checking" ? (
        <AuthSkeleton />
      ) : auth.phase === "unknown" ? (
        <Unreachable next={next} />
      ) : auth.phase === "open" ? (
        <OpenConsole next={next} />
      ) : (
        <SignInForm next={next} signedOut={signedOut} setMood={setMood} />
      )}
    </AuthLayout>
  );
}

/** `/register`, carrying `next` along when it isn't the default. */
function registerHref(next: string) {
  return next === APP ? "/register" : `/register?next=${encodeURIComponent(next)}`;
}

// ---------------------------------------------------------------------------

function OpenConsole({ next }: { next: string }) {
  const navigate = useNavigate();
  const { registration } = useAuth();
  return (
    <div>
      <AuthHeading title="The console is open">
        Access control is off on this server, so anyone with the link can use the console and place calls.
      </AuthHeading>
      <Button size="lg" className="mt-8 w-full" iconRight={<IconArrowRight size={15} />} onClick={() => navigate(next)}>
        Enter the console
      </Button>
      <p className="mt-6 text-sm leading-relaxed text-ink-secondary">
        To require a sign-in, set <code className="rounded bg-subtle px-1 py-0.5 font-mono text-[0.8125rem] text-ink">ADMIN_PASSWORD</code> on
        the server
        {registration?.mode === "owner" ? (
          <>
            , or{" "}
            <Link to={registerHref(next)} className="font-medium text-brand underline-offset-4 hover:underline">
              create the owner account
            </Link>
            .
          </>
        ) : (
          " and restart it."
        )}
      </p>
    </div>
  );
}

function Unreachable({ next }: { next: string }) {
  const navigate = useNavigate();
  const { recheck } = useAuth();
  return (
    <div>
      <AuthHeading title="Can't reach the server">
        We couldn't ask the {BRAND.name} server whether this console is locked. Check that the API is running, then
        try again.
      </AuthHeading>
      <div className="mt-8 flex flex-col gap-3">
        <Button size="lg" icon={<IconRefresh size={15} />} onClick={recheck}>
          Try again
        </Button>
        <Button size="lg" variant="secondary" onClick={() => navigate(next)}>
          Continue to the console
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

type Errors = { email?: string; password?: string; form?: string };

function SignInForm({
  next,
  signedOut,
  setMood,
}: {
  next: string;
  signedOut: boolean;
  setMood: (mood: AgentState) => void;
}) {
  const { signIn, recheck, registration } = useAuth();
  const accounts = registration !== null;
  // Before the first account exists, the admin password is the only way in.
  const ownerPending = registration?.mode === "owner";
  const [legacy, setLegacy] = useState(!accounts || ownerPending);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [forgotOpen, setForgotOpen] = useState(false);
  const cooldown = useCooldown();
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const returnTo = next === APP ? null : pageNameFor(next.split(/[?#]/)[0]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || cooldown.active) return;
    const found: Errors = {};
    if (!legacy) {
      if (!email.trim()) found.email = "Enter your email address.";
      else if (!EMAIL_SHAPE.test(email.trim())) found.email = "That doesn't look like an email address.";
    }
    if (!password) found.password = legacy ? "Enter the admin password." : "Enter your password.";
    setErrors(found);
    if (found.email) return emailRef.current?.focus();
    if (found.password) return passwordRef.current?.focus();

    setBusy(true);
    setMood("thinking");
    try {
      await signIn(legacy ? { password } : { email: email.trim(), password }, () => setMood("ended"), 900);
    } catch (err) {
      setMood("error");
      setBusy(false);
      const e = err instanceof ApiError ? err : new ApiError((err as Error).message, 0);
      if (e.status === 401) {
        setErrors({
          password: legacy
            ? "That password isn't right. Check it and try again."
            : "That email and password don't match an account. Check both and try again.",
        });
        passwordRef.current?.select();
        passwordRef.current?.focus();
      } else if (e.status === 429) {
        cooldown.start(60);
        setErrors({ form: "lockout" });
      } else if (e.status === 400 && /off/i.test(e.message)) {
        // Access control was switched off since this page loaded.
        recheck();
      } else {
        setErrors({ form: e.message || "Sign-in failed. Try again." });
      }
    }
  };

  const switchMode = () => {
    setLegacy((l) => !l);
    setErrors({});
    setPassword("");
  };

  return (
    <div>
      <AuthHeading
        eyebrow={
          <>
            <IconLock size={14} /> Protected workspace
          </>
        }
        title="Sign in"
      >
        {legacy
          ? `Enter the workspace's admin password to open the ${BRAND.name} console.`
          : `Use your ${BRAND.name} account to open the console.`}
        {returnTo && ` You'll go back to ${returnTo} afterwards.`}
      </AuthHeading>

      {signedOut && !errors.form && (
        <Callout tone="info" className="mt-6">
          You've signed out.
        </Callout>
      )}
      {errors.form === "lockout" ? (
        <Callout tone="warning" className="mt-6" title="Too many attempts">
          Wait a minute before trying again. Repeated wrong passwords from one device are slowed down on purpose.
        </Callout>
      ) : (
        errors.form && (
          <Callout tone="critical" className="mt-6">
            {errors.form}
          </Callout>
        )
      )}

      <form onSubmit={submit} className="mt-6 space-y-5" noValidate>
        {legacy ? (
          // Lets password managers file the shared password under a name.
          <input type="text" name="username" autoComplete="username" value="admin" readOnly hidden />
        ) : (
          <AuthField label="Email" error={errors.email}>
            {({ id, describedBy, invalid }) => (
              <input
                ref={emailRef}
                id={id}
                type="email"
                name="email"
                autoComplete="username"
                inputMode="email"
                autoFocus
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (errors.email) setErrors((x) => ({ ...x, email: undefined }));
                  if (!busy) setMood(e.target.value ? "listening" : "idle");
                }}
                aria-invalid={invalid}
                aria-describedby={describedBy}
                className={authInputClass}
                placeholder="you@company.com"
              />
            )}
          </AuthField>
        )}

        <AuthField
          label={legacy ? "Admin password" : "Password"}
          error={errors.password}
          aside={
            !legacy && (
              <button
                type="button"
                onClick={() => setForgotOpen((o) => !o)}
                aria-expanded={forgotOpen}
                className="rounded-sm text-xs font-medium text-ink-secondary underline-offset-4 hover:text-ink hover:underline"
              >
                Forgot?
              </button>
            )
          }
          hint={
            !legacy && forgotOpen
              ? "There's no email reset. Ask your workspace owner or an admin: they can remove your account and send you a new invite."
              : undefined
          }
        >
          {({ id, describedBy, invalid }) => (
            <PasswordInput
              ref={passwordRef}
              id={id}
              name="password"
              autoComplete="current-password"
              autoFocus={legacy}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (errors.password) setErrors((x) => ({ ...x, password: undefined }));
                if (!busy) setMood(e.target.value ? "listening" : "idle");
              }}
              onBlur={() => !busy && setMood("idle")}
              aria-invalid={invalid}
              aria-describedby={describedBy}
            />
          )}
        </AuthField>

        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={cooldown.active}>
          {busy ? "Checking…" : cooldown.active ? `Try again in ${cooldown.label}` : "Sign in"}
        </Button>
      </form>

      <div className="mt-6 space-y-3 text-sm">
        {accounts && registration.mode !== "closed" && (
          <p className="text-ink-secondary">
            {ownerPending ? "No accounts yet. " : "New here? "}
            <Link to={registerHref(next)} className="font-medium text-brand underline-offset-4 hover:underline">
              {ownerPending ? "Create the owner account" : "Create an account"}
            </Link>
          </p>
        )}
        {accounts && !ownerPending && (
          <button
            type="button"
            onClick={switchMode}
            className="rounded-sm font-medium text-ink-secondary underline-offset-4 hover:text-ink hover:underline"
          >
            {legacy ? "Sign in with your email instead" : "Use the admin password instead"}
          </button>
        )}
      </div>

      <p className="mt-8 border-t border-line pt-5 text-xs leading-relaxed text-ink-muted">
        {legacy ? (
          <>
            The admin password is the server's <code className="font-mono">ADMIN_PASSWORD</code>.{" "}
          </>
        ) : null}
        A session lasts 12 hours unless the server is set otherwise.
      </p>
    </div>
  );
}
