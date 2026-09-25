/**
 * Sign in — shown only when the backend has ADMIN_PASSWORD set.
 *
 * The agent reacts: it listens while you type, thinks while the server
 * checks, frowns at a wrong password and waves you in on success.
 */

import { useState, type FormEvent } from "react";
import { m } from "framer-motion";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { BRAND } from "../brand";
import { AgentAvatar, type AgentState } from "../components/AgentAvatar";
import { Logo } from "../components/Logo";
import { IconLock } from "../components/icons";
import { Button, Field, Input } from "../components/ui";
import { rise } from "../motion";
import { useDocumentTitle } from "../hooks";

export default function Login() {
  const { signIn } = useAuth();
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mood, setMood] = useState<AgentState>("idle");
  useDocumentTitle("Sign in");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError(null);
    setMood("thinking");
    try {
      await signIn(password, () => setMood("ended"), 900);
    } catch (err) {
      setMood("error");
      setError(
        err instanceof ApiError && err.status === 401
          ? "That password isn't right. Try again."
          : err instanceof ApiError && err.status === 429
            ? "Too many attempts. Wait a few minutes, then try again."
            : (err as Error).message,
      );
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      {/* Brand panel */}
      <div className="relative hidden overflow-hidden border-r border-line bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden
          className="pointer-events-none absolute -left-32 -top-32 h-[520px] w-[520px] rounded-full bg-brand/10 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-40 right-0 h-[420px] w-[420px] rounded-full bg-info/8 blur-3xl"
        />
        <Logo size={32} />
        <div className="relative">
          <AgentAvatar state={mood} size="lg" />
          <h1 className="mt-8 max-w-md text-3xl font-semibold leading-tight tracking-tight text-ink">
            {BRAND.tagline}
          </h1>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-ink-secondary">{BRAND.description}</p>
        </div>
        <p className="relative text-xs text-ink-muted">
          <span lang="hi">{BRAND.nativeName}</span> — “conversation”.
        </p>
      </div>

      {/* Form */}
      <div className="flex items-center justify-center px-4 py-12 sm:px-8">
        <m.div {...rise} className="w-full max-w-sm">
          <div className="mb-8 flex flex-col items-center text-center lg:hidden">
            <AgentAvatar state={mood} size="md" />
            <Logo size={28} className="mt-5" />
          </div>

          <div className="flex items-center gap-2 text-xs font-medium text-ink-muted">
            <IconLock size={14} /> Protected workspace
          </div>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink">Welcome back</h2>
          <p className="mt-1.5 text-sm text-ink-secondary">
            Enter the workspace password to open the {BRAND.name} console.
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
            {/* Lets password managers file the credential under a name. */}
            <input type="text" name="username" autoComplete="username" value="admin" readOnly hidden />
            <Field label="Password" error={error}>
              <div className="relative">
                <Input
                  type={show ? "text" : "password"}
                  autoComplete="current-password"
                  autoFocus
                  value={password}
                  aria-invalid={!!error}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError(null);
                    if (!busy) setMood(e.target.value ? "listening" : "idle");
                  }}
                  onBlur={() => !busy && mood === "listening" && setMood("idle")}
                  className="h-11 pr-16"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
                  aria-label={show ? "Hide password" : "Show password"}
                >
                  {show ? "Hide" : "Show"}
                </button>
              </div>
            </Field>
            <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!password}>
              {busy ? "Checking…" : "Sign in"}
            </Button>
          </form>

          <p className="mt-8 text-center text-xs leading-relaxed text-ink-muted">
            The password is the server's <code className="font-mono">ADMIN_PASSWORD</code>. Sessions last 12 hours by
            default.
          </p>
        </m.div>
      </div>
    </div>
  );
}
