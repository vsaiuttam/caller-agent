import type { ReactNode } from "react";
import type { Disposition, QualificationBand } from "../api";
import { IconInbox, IconTrendDown, IconTrendUp } from "./icons";

// ---------------------------------------------------------------------------
// Logo — CallerAgent mark
// ---------------------------------------------------------------------------

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      {/* Rounded square base */}
      <rect width="32" height="32" rx="8" fill="url(#logo-grad)" />
      {/* Phone handset */}
      <path
        d="M11.5 9.5C11.5 9.5 12.5 9 14 10.5C15.5 12 14 13.5 14 13.5L16.5 16L18.5 18.5C18.5 18.5 20 17 21.5 18.5C23 20 22.5 21 22.5 21L21 22.5C19.5 24 14.5 21.5 12 19C9.5 16.5 8 12.5 9.5 11L11.5 9.5Z"
        fill="white"
        opacity="0.95"
      />
      {/* Signal arcs */}
      <path d="M19 9C21.2 9.8 23 11.5 23.5 14" stroke="white" strokeWidth="1.5" strokeLinecap="round" opacity="0.7" />
      <path d="M19 12.5C20 13 21 13.8 21.2 15" stroke="white" strokeWidth="1.5" strokeLinecap="round" opacity="0.5" />
      <defs>
        <linearGradient id="logo-grad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#7C5AFF" />
          <stop offset="1" stopColor="#5B3FCC" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Spinner — clean arc
// ---------------------------------------------------------------------------

export function Spinner({ size = 24, className = "" }: { size?: number; className?: string }) {
  return (
    <svg className={`arc-spinner ${className}`} width={size} height={size} viewBox="0 0 50 50">
      <circle cx="25" cy="25" r="20" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

export function Card({
  children,
  className = "",
  hover: _hover = true,
}: {
  children: ReactNode;
  className?: string;
  hover?: boolean;
}) {
  return <div className={`card ${className}`}>{children}</div>;
}

// ---------------------------------------------------------------------------
// HeroStat
// ---------------------------------------------------------------------------

export function HeroStat({
  label,
  value,
  delta,
  caption,
  icon,
}: {
  label: string;
  value: string | number;
  delta?: number | null;
  caption?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col justify-between rounded-[10px] bg-gradient-to-br from-brand to-brand-deep p-5 text-white">
      <div className="flex items-start justify-between">
        <span className="text-sm font-medium opacity-80">{label}</span>
        {icon && <span className="opacity-30">{icon}</span>}
      </div>
      <div className="mt-auto pt-6">
        <p className="tnum text-4xl font-extrabold leading-none tracking-tight">{value}</p>
        <p className="mt-2 text-sm opacity-70">
          {delta !== undefined && delta !== null && (
            <span className="mr-1.5 font-semibold">
              {delta > 0 ? "\u2191" : "\u2193"} {Math.abs(Math.round(delta * 100))}%
            </span>
          )}
          {caption}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CardHeader
// ---------------------------------------------------------------------------

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--surface-border)] px-5 py-3.5">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat
// ---------------------------------------------------------------------------

export function Stat({
  label,
  value,
  delta,
  hint,
  icon,
  tone = "neutral",
  deltaGoodDirection = "up",
}: {
  label: string;
  value: string | number;
  delta?: number | null;
  hint?: string;
  icon?: ReactNode;
  tone?: "neutral" | "attention";
  deltaGoodDirection?: "up" | "down";
}) {
  return (
    <Card className={`px-4 py-3.5 ${tone === "attention" ? "!border-warning/30" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-ink-muted">{label}</p>
        {icon && <span className={tone === "attention" ? "text-warning" : "text-ink-muted/70"}>{icon}</span>}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="tnum text-2xl font-bold leading-none">{value}</span>
        {delta !== undefined && <DeltaBadge value={delta} goodDirection={deltaGoodDirection} />}
      </div>
      {hint && <p className="mt-1.5 text-xs text-ink-muted">{hint}</p>}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// DeltaBadge
// ---------------------------------------------------------------------------

export function DeltaBadge({
  value,
  goodDirection,
}: {
  value: number | null;
  goodDirection: "up" | "down";
}) {
  if (value === null || value === 0) return <span className="text-xs text-ink-muted">&mdash;</span>;

  const rising = value > 0;
  const isGood = goodDirection === "up" ? rising : !rising;
  const cls = isGood ? "text-good bg-good/10" : "text-critical bg-critical/10";

  return (
    <span className={`tnum inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {rising ? <IconTrendUp size={12} /> : <IconTrendDown size={12} />}
      {Math.abs(Math.round(value * 100))}%
    </span>
  );
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

export function Button({
  children,
  onClick,
  variant = "primary",
  size = "md",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const v = {
    primary: "bg-brand text-white font-semibold hover:bg-brand-bright active:scale-[0.98]",
    secondary: "card hover:border-brand/30",
    danger: "bg-critical text-white hover:brightness-110 active:scale-[0.98]",
    ghost: "text-ink-secondary hover:bg-elevated hover:text-ink",
  };
  const s = {
    sm: "px-3 py-1.5 text-xs gap-1.5",
    md: "px-4 py-2 text-sm gap-2",
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center rounded-lg transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40 ${v[variant]} ${s[size]}`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// DispositionBadge
// ---------------------------------------------------------------------------

const DISP: Record<Disposition, { label: string; cls: string }> = {
  completed:          { label: "Completed",    cls: "bg-good/10 text-good border-good/20" },
  partial:            { label: "Partial",      cls: "bg-warning/10 text-warning border-warning/20" },
  callback_requested: { label: "Callback",     cls: "bg-warning/10 text-warning border-warning/20" },
  declined:           { label: "Declined",     cls: "bg-serious/10 text-serious border-serious/20" },
  do_not_call:        { label: "Do not call",  cls: "bg-critical text-white border-critical/50" },
  failed:             { label: "Failed",       cls: "bg-critical/10 text-critical border-critical/20" },
  voicemail:          { label: "Voicemail",    cls: "bg-white/5 text-ink-secondary border-white/8" },
  no_answer:          { label: "No answer",    cls: "bg-white/5 text-ink-secondary border-white/8" },
  wrong_number:       { label: "Wrong number", cls: "bg-white/5 text-ink-secondary border-white/8" },
};

export function DispositionBadge({ value }: { value: Disposition | null }) {
  if (!value) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-brand/20 bg-brand/8 px-2 py-0.5 text-xs text-brand">
        <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-brand" />
        In progress
      </span>
    );
  }
  const m = DISP[value];
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${m.cls}`}>
      {m.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ScoreBadge
// ---------------------------------------------------------------------------

const BAND: Record<QualificationBand, { label: string; cls: string }> = {
  strong:        { label: "Strong",       cls: "bg-good/10 text-good border-good/20" },
  possible:      { label: "Possible",     cls: "bg-warning/10 text-warning border-warning/20" },
  weak:          { label: "Weak",         cls: "bg-serious/10 text-serious border-serious/20" },
  disqualified:  { label: "Disqualified", cls: "bg-critical/10 text-critical border-critical/20" },
  not_assessed:  { label: "Not scored",   cls: "bg-white/5 text-ink-secondary border-white/8" },
};

export function ScoreBadge({
  score,
  band,
  size = "md",
}: {
  score: number | null;
  band: QualificationBand | null;
  size?: "sm" | "md";
}) {
  if (!band || band === "not_assessed") return <span className="text-xs text-ink-muted">&mdash;</span>;
  const m = BAND[band];
  const p = size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2 py-0.5 text-xs";
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border font-medium ${p} ${m.cls}`}>
      {band !== "disqualified" && score !== null && <span className="tnum font-bold">{score}</span>}
      {m.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------

export function StatusBadge({ status }: { status: string }) {
  const t =
    status === "running"  ? "bg-good/10 text-good border-good/20"
    : status === "paused" ? "bg-warning/10 text-warning border-warning/20"
    :                       "bg-white/5 text-ink-secondary border-white/8";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium capitalize ${t}`}>
      {status === "running" && <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-good" />}
      {status}
    </span>
  );
}

export function LiveDot() {
  return <span className="live-dot inline-block h-2 w-2 rounded-full bg-good" />;
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

export function EmptyState({
  title,
  hint,
  action,
  loading,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  loading?: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {loading ? <Spinner size={32} /> : <span className="text-ink-muted/30"><IconInbox size={36} /></span>}
      <p className="mt-3 text-sm font-semibold">{title}</p>
      {hint && <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-ink-muted">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field
// ---------------------------------------------------------------------------

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-ink-secondary">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "mt-1 w-full rounded-lg border border-[var(--surface-border)] bg-white/[0.03] px-3 py-2 text-sm outline-none transition-all duration-150 placeholder:text-ink-muted/50 focus:border-brand/50 focus:ring-2 focus:ring-brand/15";

// ---------------------------------------------------------------------------
// ErrorNote
// ---------------------------------------------------------------------------

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-critical/20 bg-critical/8 px-4 py-3 text-xs text-critical">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-critical" />
      {message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`shimmer ${className}`} />;
}

// ---------------------------------------------------------------------------
// PageWrapper
// ---------------------------------------------------------------------------

export function PageWrapper({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`page-enter ${className}`}>{children}</div>;
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "\u2014";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
