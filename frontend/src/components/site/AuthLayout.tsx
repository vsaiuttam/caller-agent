/**
 * The frame /login and /register share: the public header (no call to
 * action; you're already here), a two-panel card with the agent reacting on
 * the left from 1024px, the form on the right, then the marketing footer.
 * Also the small form parts both pages use, so their fields, errors and
 * lockout behave identically.
 */

import { useEffect, useId, useState, type InputHTMLAttributes, type ReactNode, type Ref } from "react";
import { m } from "framer-motion";
import { BRAND } from "../../brand";
import { rise } from "../../motion";
import { AgentAvatar, type AgentState } from "../AgentAvatar";
import { IconAlert, IconEye, IconEyeOff } from "../icons";
import { Skeleton, cx, inputClass } from "../ui";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader, SkipLink } from "./SiteHeader";

export function AuthLayout({ mood, children }: { mood: AgentState; children: ReactNode }) {
  return (
    <div className="flex min-h-[100dvh] flex-col">
      <SkipLink />
      <SiteHeader cta={false} />
      <main id="main" tabIndex={-1} className="flex flex-1 items-start justify-center px-4 py-10 outline-none sm:px-6 sm:py-16 lg:items-center">
        <div className="grid w-full max-w-5xl overflow-hidden rounded-2xl border border-line bg-surface elev-2 lg:grid-cols-[1fr_1.1fr]">
          {/* Brand panel */}
          <div className="relative hidden flex-col justify-between overflow-hidden border-r border-line bg-subtle/60 p-10 lg:flex xl:p-12">
            <div aria-hidden className="flame-glow absolute -left-24 -top-24 h-[28rem] w-[28rem]" />
            <div className="relative">
              <AgentAvatar state={mood} size="lg" />
              <p className="mt-8 max-w-sm text-display-md font-semibold text-ink">{BRAND.tagline}</p>
              <p className="mt-3 max-w-sm text-sm leading-relaxed text-ink-secondary">{BRAND.description}</p>
            </div>
            <p className="relative mt-10 text-xs text-ink-muted">
              <span lang="hi">{BRAND.nativeName}</span> means “{BRAND.meaning}”.
            </p>
          </div>

          {/* Form panel */}
          <div className="px-5 py-8 sm:px-10 sm:py-12 xl:px-14">
            <m.div {...rise} className="mx-auto w-full max-w-sm">
              <div className="mb-6 flex justify-center lg:hidden">
                <AgentAvatar state={mood} size="md" />
              </div>
              {children}
            </m.div>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

export function AuthHeading({ eyebrow, title, children }: { eyebrow?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div>
      {eyebrow && <div className="mb-2 flex items-center gap-2 text-xs font-medium text-ink-muted">{eyebrow}</div>}
      <h1 className="text-display-md font-semibold text-ink">{title}</h1>
      {children && <p className="mt-2 text-sm leading-relaxed text-ink-secondary">{children}</p>}
    </div>
  );
}

/** Label above, control, then an error (announced) or a hint below, all wired with ids. */
export function AuthField({
  label,
  hint,
  error,
  aside,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  /** Something on the label's line, right-aligned (a "Forgot?" button). */
  aside?: ReactNode;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {label}
        </label>
        {aside}
      </div>
      {children({ id, describedBy, invalid: !!error })}
      {error && (
        <p id={errorId} role="alert" className="mt-1.5 flex items-start gap-1.5 text-sm text-critical">
          <IconAlert size={14} className="mt-0.5 shrink-0" />
          {error}
        </p>
      )}
      {hint && (
        <div id={hintId} className="mt-1.5 text-xs leading-relaxed text-ink-muted">
          {hint}
        </div>
      )}
    </div>
  );
}

export const authInputClass = cx(inputClass, "h-11");

/** A password box with a Show/Hide toggle. Paste and password managers work. */
export function PasswordInput({
  className = "",
  ref,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { ref?: Ref<HTMLInputElement> }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <input ref={ref} type={shown ? "text" : "password"} className={cx(authInputClass, "pr-20", className)} {...rest} />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-pressed={shown}
        aria-label={shown ? "Hide password" : "Show password"}
        aria-controls={rest.id}
        className="absolute right-1.5 top-1/2 flex h-8 -translate-y-1/2 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-ink-secondary transition-colors hover:bg-subtle hover:text-ink"
      >
        {shown ? <IconEyeOff size={14} /> : <IconEye size={14} />}
        {shown ? "Hide" : "Show"}
      </button>
    </div>
  );
}

export function AuthSkeleton() {
  return (
    <div aria-busy="true" aria-label="Checking whether this console is locked">
      <Skeleton className="h-3 w-28" />
      <Skeleton className="mt-3 h-8 w-48" />
      <Skeleton className="mt-3 h-4 w-full" />
      <Skeleton className="mt-8 h-4 w-20" />
      <Skeleton className="mt-2 h-11 w-full" />
      <Skeleton className="mt-5 h-4 w-20" />
      <Skeleton className="mt-2 h-11 w-full" />
      <Skeleton className="mt-6 h-11 w-full" />
    </div>
  );
}

/**
 * After a 429: a countdown before the form accepts another try. The server
 * forgets failures after five minutes; a minute is enough to make guessing
 * slow without trapping someone who just mistyped.
 */
export function useCooldown() {
  const [until, setUntil] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return;
    const id = window.setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= until) setUntil(null);
    }, 1000);
    return () => window.clearInterval(id);
  }, [until]);
  const remaining = until ? Math.max(0, Math.ceil((until - now) / 1000)) : 0;
  return {
    active: remaining > 0,
    label: `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`,
    start: (seconds = 60) => {
      setNow(Date.now());
      setUntil(Date.now() + seconds * 1000);
    },
  };
}

export const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
