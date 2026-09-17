import type { ReactNode } from "react";
import type { Disposition, QualificationBand } from "../api";
import { IconInbox, IconTrendDown, IconTrendUp } from "./icons";

// ---------------------------------------------------------------------------
// Card — flat surface with warm border
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
  return (
    <div className={`card rounded-lg ${className}`}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HeroStat — the one bold element per screen, solid amber
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
    <div className="flex h-full flex-col justify-between rounded-lg bg-brand p-4 text-plane sm:p-5">
      <div className="flex items-start justify-between">
        <span className="text-sm font-medium opacity-75">{label}</span>
        {icon && <span className="hidden opacity-30 sm:block">{icon}</span>}
      </div>

      <div className="mt-auto pt-4 sm:pt-6">
        <p className="tnum text-2xl font-bold leading-none tracking-tight sm:text-4xl">
          {value}
        </p>
        <p className="mt-2 text-sm opacity-70">
          {delta !== undefined && delta !== null && (
            <span className="mr-1.5 font-medium">
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
    <div className="flex items-start justify-between gap-4 border-b border-white/5 px-5 py-3.5">
      <div>
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat tile — KPI with optional trend
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
  const attention = tone === "attention";

  return (
    <Card className={`px-4 py-3.5 ${attention ? "!border-warning/30" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-ink-muted">{label}</p>
        {icon && <span className={attention ? "text-warning" : "text-ink-muted/70"}>{icon}</span>}
      </div>

      <div className="mt-2 flex items-baseline gap-2">
        <span className="tnum text-2xl font-bold leading-none tracking-tight">
          {value}
        </span>
        {delta !== undefined && (
          <DeltaBadge value={delta} goodDirection={deltaGoodDirection} />
        )}
      </div>

      {hint && <p className="mt-1.5 text-xs text-ink-muted">{hint}</p>}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// DeltaBadge — trend indicator
// ---------------------------------------------------------------------------

export function DeltaBadge({
  value,
  goodDirection,
}: {
  value: number | null;
  goodDirection: "up" | "down";
}) {
  if (value === null || value === 0) {
    return <span className="text-xs text-ink-muted">&mdash;</span>;
  }

  const rising = value > 0;
  const isGood = goodDirection === "up" ? rising : !rising;
  const colour = isGood ? "text-good" : "text-critical";
  const bg = isGood ? "bg-good/10" : "bg-critical/10";

  return (
    <span className={`tnum inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs font-medium ${colour} ${bg}`}>
      {rising ? <IconTrendUp size={12} /> : <IconTrendDown size={12} />}
      {Math.abs(Math.round(value * 100))}%
    </span>
  );
}

// ---------------------------------------------------------------------------
// Button — solid fills, CSS transitions
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
  const variants = {
    primary: "bg-brand text-plane font-semibold hover:bg-brand-bright active:scale-[0.98]",
    secondary: "card hover:border-brand/30",
    danger: "bg-critical text-white hover:brightness-110 active:scale-[0.98]",
    ghost: "text-ink-secondary hover:bg-elevated hover:text-ink",
  };
  const sizes = {
    sm: "px-3 py-1.5 text-xs gap-1.5",
    md: "px-4 py-2 text-sm gap-2",
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center rounded-lg transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40 ${variants[variant]} ${sizes[size]}`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// DispositionBadge
// ---------------------------------------------------------------------------

const DISPOSITION_META: Record<Disposition, { label: string; className: string }> = {
  completed: { label: "Completed", className: "bg-good/10 text-good border-good/20" },
  partial: { label: "Partial", className: "bg-warning/10 text-warning border-warning/20" },
  callback_requested: {
    label: "Callback",
    className: "bg-warning/10 text-warning border-warning/20",
  },
  declined: { label: "Declined", className: "bg-serious/10 text-serious border-serious/20" },
  do_not_call: {
    label: "Do not call",
    className: "bg-critical text-white border-critical/50",
  },
  failed: { label: "Failed", className: "bg-critical/10 text-critical border-critical/20" },
  voicemail: {
    label: "Voicemail",
    className: "bg-white/5 text-ink-secondary border-white/10",
  },
  no_answer: {
    label: "No answer",
    className: "bg-white/5 text-ink-secondary border-white/10",
  },
  wrong_number: {
    label: "Wrong number",
    className: "bg-white/5 text-ink-secondary border-white/10",
  },
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
  const meta = DISPOSITION_META[value];
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${meta.className}`}>
      {meta.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ScoreBadge — qualification result
// ---------------------------------------------------------------------------

const BAND_META: Record<QualificationBand, { label: string; className: string }> = {
  strong: { label: "Strong", className: "bg-good/10 text-good border-good/20" },
  possible: { label: "Possible", className: "bg-warning/10 text-warning border-warning/20" },
  weak: { label: "Weak", className: "bg-serious/10 text-serious border-serious/20" },
  disqualified: {
    label: "Disqualified",
    className: "bg-critical/10 text-critical border-critical/20",
  },
  not_assessed: {
    label: "Not scored",
    className: "bg-white/5 text-ink-secondary border-white/10",
  },
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
  if (!band || band === "not_assessed") {
    return <span className="text-xs text-ink-muted">&mdash;</span>;
  }

  const meta = BAND_META[band];
  const padding = size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2 py-0.5 text-xs";

  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border font-medium ${padding} ${meta.className}`}>
      {band !== "disqualified" && score !== null && (
        <span className="tnum font-bold">{score}</span>
      )}
      {meta.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "running"
      ? "bg-good/10 text-good border-good/20"
      : status === "paused"
        ? "bg-warning/10 text-warning border-warning/20"
        : "bg-white/5 text-ink-secondary border-white/10";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium capitalize ${tone}`}>
      {status === "running" && (
        <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-good" />
      )}
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
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <span className="text-ink-muted/30">
        <IconInbox size={36} />
      </span>
      <p className="mt-3 text-sm font-semibold">{title}</p>
      {hint && (
        <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-ink-muted">{hint}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field — form input wrapper (sentence case, not uppercase)
// ---------------------------------------------------------------------------

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-semibold text-ink-secondary">{label}</span>
      {children}
      {hint && (
        <span className="mt-1 block text-xs text-ink-muted">{hint}</span>
      )}
    </label>
  );
}

export const inputClass =
  "mt-1 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none transition-all duration-150 placeholder:text-ink-muted/50 focus:border-brand/50 focus:bg-white/8 focus:ring-2 focus:ring-brand/20";

// ---------------------------------------------------------------------------
// ErrorNote
// ---------------------------------------------------------------------------

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-critical/20 bg-critical/8 px-4 py-3 text-xs text-critical">
      <span className="h-1.5 w-1.5 rounded-full bg-critical" />
      {message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton — shimmer loading
// ---------------------------------------------------------------------------

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`shimmer rounded-lg ${className}`} />;
}

// ---------------------------------------------------------------------------
// PageWrapper — simple container, no animation
// ---------------------------------------------------------------------------

export function PageWrapper({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={className}>{children}</div>;
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
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
