/**
 * The component vocabulary. Every page is built from these; if a page needs
 * a new kind of thing, it goes here first so the next page gets it too.
 *
 *   Layout      Page, PageHeader, Card, CardHeader, Section
 *   Actions     Button, ButtonLink, IconButton
 *   Inputs      Field, Input, SecretInput, Textarea, Select, Switch, Segmented, Tabs
 *   Status      Badge (+ Disposition/Score/Status/Followup/Sentiment/Test), DeltaBadge
 *   Feedback    Callout, ErrorNote, EmptyState, Skeleton, Spinner, Stat, Kbd, CodeBlock
 *   Overlays    Dialog, Drawer, Popover, Tooltip   (./overlay)
 *   Toasts      toast, Toaster                     (./toast)
 */

import {
  useId,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { Link, type LinkProps } from "react-router-dom";
import { m } from "framer-motion";
import type { Disposition, FollowupChannel, QualificationBand, Sentiment } from "../api";
import { AgentAvatar, type AgentState } from "./AgentAvatar";
import {
  IconAlert,
  IconArrowLeft,
  IconCheck,
  IconChevronDown,
  IconCopy,
  IconEye,
  IconEyeOff,
  IconFlask,
  IconFrown,
  IconInfo,
  IconMeh,
  IconRefresh,
  IconSmile,
  IconTrendDown,
  IconTrendUp,
} from "./icons";
import { Tooltip } from "./overlay";
import { toast } from "./toast";
import { rise } from "../motion";

export { Dialog, Drawer, Popover, Tooltip } from "./overlay";
export { toast, Toaster } from "./toast";

export const cx = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(" ");

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const PAGE_WIDTH = {
  narrow: "max-w-3xl",
  default: "max-w-6xl",
  wide: "max-w-[1400px]",
} as const;

/** The page container: consistent gutters, max width and an entrance. */
export function Page({
  children,
  width = "default",
  className = "",
}: {
  children: ReactNode;
  width?: keyof typeof PAGE_WIDTH;
  className?: string;
}) {
  return (
    <m.div
      initial={rise.initial}
      animate={rise.animate}
      transition={rise.transition}
      className={cx("mx-auto w-full px-4 pb-16 pt-6 sm:px-6 lg:px-8", PAGE_WIDTH[width], className)}
    >
      {children}
    </m.div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  icon,
  back,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  back?: { to: string; label: string };
  /** Badges beside the title. */
  meta?: ReactNode;
}) {
  return (
    <header className="mb-6">
      {back && (
        <Link
          to={back.to}
          className="mb-3 inline-flex items-center gap-1.5 rounded-md text-xs font-medium text-ink-muted transition-colors hover:text-ink"
        >
          <IconArrowLeft size={13} /> {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 items-start gap-3">
          {icon && (
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-brand elev-1">
              {icon}
            </span>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">{title}</h1>
              {meta}
            </div>
            {description && (
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-secondary">{description}</p>
            )}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export function Card({
  children,
  className = "",
  interactive = false,
}: {
  children: ReactNode;
  className?: string;
  /** Hover lift, for cards that are links or buttons. */
  interactive?: boolean;
}) {
  return <div className={cx("card", interactive && "card-interactive", className)}>{children}</div>;
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <span className="mt-0.5 text-ink-muted">{icon}</span>}
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  );
}

/** A small uppercase label over a group of content inside a card. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <p className={cx("text-2xs font-medium uppercase tracking-wider text-ink-muted", className)}>{children}</p>;
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

export type ButtonVariant = "primary" | "secondary" | "ghost" | "subtle" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-brand text-on-brand hover:bg-brand-hover elev-1 shadow-[inset_0_1px_0_rgb(255_255_255/0.14)]",
  secondary: "border border-line-strong bg-surface text-ink hover:bg-subtle elev-1",
  ghost: "text-ink-secondary hover:bg-subtle hover:text-ink",
  subtle: "bg-subtle text-ink hover:bg-subtle-strong",
  danger: "bg-critical text-on-critical hover:brightness-110 elev-1",
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 px-2.5 text-xs",
  md: "h-9 gap-2 px-3.5 text-sm",
  lg: "h-11 gap-2 px-5 text-sm",
};

export function buttonClass(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  extra = "",
): string {
  return cx(
    "inline-flex select-none items-center justify-center whitespace-nowrap rounded-md font-medium",
    "transition-[background-color,border-color,color,box-shadow,filter,transform] duration-150",
    "active:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50",
    BUTTON_VARIANT[variant],
    BUTTON_SIZE[size],
    extra,
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner in place of the icon and blocks clicks. */
  loading?: boolean;
  icon?: ReactNode;
  iconRight?: ReactNode;
  ref?: Ref<HTMLButtonElement>;
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  iconRight,
  className = "",
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
      {iconRight}
    </button>
  );
}

export function ButtonLink({
  variant = "primary",
  size = "md",
  icon,
  iconRight,
  className = "",
  children,
  ...rest
}: LinkProps & { variant?: ButtonVariant; size?: ButtonSize; icon?: ReactNode; iconRight?: ReactNode }) {
  return (
    <Link className={buttonClass(variant, size, className)} {...rest}>
      {icon}
      {children}
      {iconRight}
    </Link>
  );
}

/** Icon-only button. `label` is both the accessible name and the tooltip. */
export function IconButton({
  label,
  icon,
  size = "md",
  variant = "ghost",
  tooltip = true,
  tooltipSide = "bottom",
  className = "",
  ...rest
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  label: string;
  icon: ReactNode;
  size?: "sm" | "md";
  variant?: ButtonVariant;
  tooltip?: boolean;
  tooltipSide?: "top" | "bottom" | "right";
}) {
  const button = (
    <button
      type="button"
      aria-label={label}
      className={cx(
        buttonClass(variant, size),
        size === "sm" ? "h-8 w-8 !px-0" : "h-9 w-9 !px-0",
        className,
      )}
      {...rest}
    >
      {icon}
    </button>
  );
  return tooltip ? (
    <Tooltip content={label} side={tooltipSide}>
      {button}
    </Tooltip>
  ) : (
    button
  );
}

/** Only inside buttons — content loading uses skeletons. */
export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin" aria-hidden>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Form controls
// ---------------------------------------------------------------------------

export const inputClass = cx(
  "w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-ink",
  "placeholder:text-ink-muted/80 transition-[border-color,box-shadow] duration-150",
  "hover:border-ink-muted/60 focus:border-brand focus:outline-none focus:ring-3 focus:ring-brand/20",
  "disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-critical",
);

/**
 * A labelled control. Wraps the control in a <label> by default; pass
 * `group` when the children are several controls (chips, toggles) so the
 * label doesn't hijack clicks meant for the first of them.
 */
export function Field({
  label,
  hint,
  error,
  children,
  group = false,
  className = "",
  optional = false,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  group?: boolean;
  className?: string;
  optional?: boolean;
}) {
  const id = useId();
  const labelText = (
    <span className="mb-1.5 flex items-baseline justify-between gap-2 text-xs font-medium text-ink-secondary">
      <span id={`${id}-label`}>{label}</span>
      {optional && <span className="font-normal text-ink-muted">Optional</span>}
    </span>
  );
  const after = (
    <>
      {error ? (
        <span role="alert" className="mt-1.5 flex items-center gap-1 text-xs text-critical">
          <IconAlert size={12} /> {error}
        </span>
      ) : (
        hint && <span className="mt-1.5 block text-xs leading-relaxed text-ink-muted">{hint}</span>
      )}
    </>
  );

  if (group) {
    return (
      <div role="group" aria-labelledby={`${id}-label`} className={cx("block", className)}>
        {labelText}
        {children}
        {after}
      </div>
    );
  }
  return (
    <label className={cx("block", className)}>
      {labelText}
      {children}
      {after}
    </label>
  );
}

export function Input({
  className = "",
  ref,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return <input ref={ref} className={cx(inputClass, "h-9", className)} {...rest} />;
}

/**
 * A password-style field with a reveal toggle, for API keys and URLs that
 * carry one. Password managers are asked not to offer to save it.
 */
export function SecretInput({
  className = "",
  ref,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { ref?: Ref<HTMLInputElement> }) {
  const [shown, setShown] = useState(false);
  return (
    <span className={cx("relative block", className)}>
      <input
        ref={ref}
        type={shown ? "text" : "password"}
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        data-1p-ignore
        data-lpignore="true"
        className={cx(inputClass, "h-9 pr-10 font-mono text-[0.8125rem]")}
        {...rest}
      />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide value" : "Show value"}
        aria-pressed={shown}
        disabled={rest.disabled}
        className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-subtle hover:text-ink disabled:opacity-50"
      >
        {shown ? <IconEyeOff size={15} /> : <IconEye size={15} />}
      </button>
    </span>
  );
}

export function Textarea({
  className = "",
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx(inputClass, "min-h-20 resize-y py-2 leading-relaxed", className)} {...rest} />;
}

export function Select({
  className = "",
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={cx("relative block", className)}>
      <select className={cx(inputClass, "h-9 cursor-pointer appearance-none pr-9")} {...rest}>
        {children}
      </select>
      <IconChevronDown
        size={14}
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-muted"
      />
    </span>
  );
}

/** On/off switch. The whole row is the hit target. */
export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled = false,
  className = "",
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cx("flex items-start justify-between gap-4", disabled && "opacity-60", className)}>
      <div className="min-w-0">
        <label htmlFor={id} className="cursor-pointer text-sm font-medium text-ink">
          {label}
        </label>
        {description && <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-200",
          checked ? "border-brand bg-brand" : "border-line-strong bg-subtle-strong",
        )}
      >
        <span
          className={cx(
            "inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ease-[var(--ease-out)]",
            checked ? "translate-x-[17px]" : "translate-x-[1px]",
          )}
        />
      </button>
    </div>
  );
}

/** Arrow-key navigation shared by radio groups and tab lists. */
function rovingKeys<T>(event: KeyboardEvent, values: T[], current: T, select: (value: T) => void) {
  const index = values.indexOf(current);
  const next =
    event.key === "ArrowRight" || event.key === "ArrowDown"
      ? (index + 1) % values.length
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? (index - 1 + values.length) % values.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? values.length - 1
            : -1;
  if (next < 0) return;
  event.preventDefault();
  select(values[next]);
  const group = event.currentTarget as HTMLElement;
  requestAnimationFrame(() => group.querySelectorAll<HTMLElement>("[data-roving]")[next]?.focus());
}

/** A compact single-choice control (sort order, density, filters). */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
  className = "",
}: {
  value: T;
  onChange: (value: T) => void;
  options: Array<{ value: T; label: ReactNode; icon?: ReactNode; title?: string }>;
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      onKeyDown={(e) => rovingKeys(e, options.map((o) => o.value), value, onChange)}
      className={cx("inline-flex rounded-lg border border-line bg-subtle p-0.5", className)}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.title}
            tabIndex={active ? 0 : -1}
            data-roving
            onClick={() => onChange(option.value)}
            className={cx(
              "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-[background-color,color,box-shadow] duration-150",
              size === "sm" ? "h-7 px-2 text-xs" : "h-8 px-3 text-xs",
              active ? "bg-surface text-ink elev-1" : "text-ink-secondary hover:text-ink",
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/** In-page tabs (not routes). */
export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
  label,
  className = "",
}: {
  value: T;
  onChange: (value: T) => void;
  tabs: Array<{ value: T; label: ReactNode; icon?: ReactNode; count?: number }>;
  label: string;
  className?: string;
}) {
  const baseId = useId();
  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={(e) => rovingKeys(e, tabs.map((t) => t.value), value, onChange)}
      className={cx("flex gap-1 overflow-x-auto border-b border-line scrollbar-none", className)}
    >
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            id={`${baseId}-${tab.value}`}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            data-roving
            onClick={() => onChange(tab.value)}
            className={cx(
              "relative -mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 px-3 text-sm font-medium transition-colors duration-150",
              active
                ? "border-brand text-ink"
                : "border-transparent text-ink-muted hover:border-line-strong hover:text-ink",
            )}
          >
            {tab.icon}
            {tab.label}
            {tab.count !== undefined && (
              <span className="tnum rounded-full bg-subtle px-1.5 text-2xs text-ink-secondary">{tab.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

export type Tone = "neutral" | "brand" | "good" | "warning" | "serious" | "critical" | "info";

const BADGE_TONE: Record<Tone, string> = {
  neutral: "border-line bg-subtle text-ink-secondary",
  brand: "border-brand/25 bg-brand/10 text-brand",
  good: "border-good/25 bg-good/10 text-good",
  warning: "border-warning/30 bg-warning/10 text-warning",
  serious: "border-serious/25 bg-serious/10 text-serious",
  critical: "border-critical/25 bg-critical/10 text-critical",
  info: "border-info/25 bg-info/10 text-info",
};

export function Badge({
  tone = "neutral",
  children,
  dot = false,
  pulse = false,
  icon,
  className = "",
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  pulse?: boolean;
  icon?: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full border px-2 text-2xs font-medium",
        BADGE_TONE[tone],
        className,
      )}
    >
      {dot && <span className={cx("h-1.5 w-1.5 rounded-full bg-current", pulse && "live-dot")} />}
      {icon}
      {children}
    </span>
  );
}

const DISPOSITION_META: Record<Disposition, { label: string; tone: Tone }> = {
  completed: { label: "Completed", tone: "good" },
  partial: { label: "Partial", tone: "warning" },
  callback_requested: { label: "Callback", tone: "warning" },
  declined: { label: "Declined", tone: "serious" },
  do_not_call: { label: "Do not call", tone: "critical" },
  failed: { label: "Failed", tone: "critical" },
  voicemail: { label: "Voicemail", tone: "neutral" },
  no_answer: { label: "No answer", tone: "neutral" },
  wrong_number: { label: "Wrong number", tone: "neutral" },
};

export const dispositionLabel = (value: string) =>
  DISPOSITION_META[value as Disposition]?.label ?? value.replace(/_/g, " ");

export function DispositionBadge({ value }: { value: Disposition | null }) {
  if (!value) {
    return (
      <Badge tone="brand" dot pulse>
        In progress
      </Badge>
    );
  }
  const meta = DISPOSITION_META[value] ?? { label: value, tone: "neutral" as Tone };
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

const BAND_META: Record<QualificationBand, { label: string; tone: Tone }> = {
  strong: { label: "Strong", tone: "good" },
  possible: { label: "Possible", tone: "warning" },
  weak: { label: "Weak", tone: "serious" },
  disqualified: { label: "Disqualified", tone: "critical" },
  not_assessed: { label: "Not scored", tone: "neutral" },
};

export function ScoreBadge({ score, band }: { score: number | null; band: QualificationBand | null }) {
  if (!band || band === "not_assessed") return <span className="text-xs text-ink-muted">—</span>;
  const meta = BAND_META[band];
  return (
    <Badge tone={meta.tone}>
      {band !== "disqualified" && score !== null && <span className="tnum font-semibold">{score}</span>}
      {meta.label}
    </Badge>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Tone = status === "running" ? "good" : status === "paused" ? "warning" : "neutral";
  return (
    <Badge tone={tone} dot={status === "running"} pulse={status === "running"} className="capitalize">
      {status}
    </Badge>
  );
}

const FOLLOWUP_TONE: Record<string, Tone> = {
  delivered: "good",
  read: "good",
  failed: "critical",
  undelivered: "critical",
};

export function FollowupBadge({ channel, status }: { channel: FollowupChannel; status: string }) {
  return (
    <Badge tone={FOLLOWUP_TONE[status] ?? "info"}>
      {channel === "sms" ? "SMS" : "WhatsApp"}
      <span className="capitalize opacity-80">· {status}</span>
    </Badge>
  );
}

const SENTIMENT_META: Record<Sentiment, { label: string; tone: Tone; icon: ReactNode }> = {
  positive: { label: "Positive", tone: "good", icon: <IconSmile size={12} /> },
  neutral: { label: "Neutral", tone: "neutral", icon: <IconMeh size={12} /> },
  negative: { label: "Negative", tone: "critical", icon: <IconFrown size={12} /> },
};

export function SentimentBadge({ value, title }: { value: Sentiment | null | undefined; title?: string }) {
  if (!value || !SENTIMENT_META[value]) return null;
  const meta = SENTIMENT_META[value];
  return (
    <Badge tone={meta.tone} icon={meta.icon} title={title}>
      {meta.label}
    </Badge>
  );
}

export function TestBadge() {
  return (
    <Badge tone="neutral" icon={<IconFlask size={10} />} title="Test call — excluded from every metric">
      Test
    </Badge>
  );
}

export function DeltaBadge({
  value,
  goodDirection = "up",
}: {
  value: number | null | undefined;
  goodDirection?: "up" | "down";
}) {
  if (value === null || value === undefined || value === 0) {
    return (
      <span className="text-xs text-ink-muted" title="No baseline to compare against">
        —
      </span>
    );
  }
  const rising = value > 0;
  const good = goodDirection === "up" ? rising : !rising;
  return (
    <span
      className={cx(
        "tnum inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-2xs font-medium",
        good ? "bg-good/10 text-good" : "bg-critical/10 text-critical",
      )}
      title="Compared with the previous 24 hours"
    >
      {rising ? <IconTrendUp size={12} /> : <IconTrendDown size={12} />}
      {Math.abs(Math.round(value * 100))}%
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong bg-surface px-1 font-sans text-2xs font-medium text-ink-secondary shadow-[0_1px_0_var(--color-line-strong)]">
      {children}
    </kbd>
  );
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

const CALLOUT_TONE = {
  info: { className: "border-info/25 bg-info/6", icon: <IconInfo size={16} />, iconClass: "text-info" },
  good: { className: "border-good/25 bg-good/6", icon: <IconCheck size={16} />, iconClass: "text-good" },
  warning: { className: "border-warning/30 bg-warning/8", icon: <IconAlert size={16} />, iconClass: "text-warning" },
  critical: { className: "border-critical/25 bg-critical/6", icon: <IconAlert size={16} />, iconClass: "text-critical" },
} as const;

export function Callout({
  tone = "info",
  title,
  children,
  action,
  className = "",
}: {
  tone?: keyof typeof CALLOUT_TONE;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const meta = CALLOUT_TONE[tone];
  return (
    <div
      role={tone === "critical" ? "alert" : undefined}
      className={cx("flex items-start gap-3 rounded-lg border px-4 py-3", meta.className, className)}
    >
      <span className={cx("mt-0.5 shrink-0", meta.iconClass)}>{meta.icon}</span>
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-medium text-ink">{title}</p>}
        {children && <div className={cx("leading-relaxed text-ink-secondary", title ? "mt-0.5 text-xs" : "text-sm")}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** A failed load, with a retry when there's something to retry. */
export function ErrorNote({ message, onRetry, title }: { message: string; onRetry?: () => void; title?: string }) {
  return (
    <Callout
      tone="critical"
      title={title ?? "That didn't load"}
      action={
        onRetry && (
          <Button size="sm" variant="secondary" icon={<IconRefresh size={13} />} onClick={onRetry}>
            Retry
          </Button>
        )
      }
    >
      {message}
    </Callout>
  );
}

export function EmptyState({
  title,
  hint,
  action,
  avatar = "idle",
  icon,
  compact = false,
}: {
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  /** The agent character's pose, or false for an icon/nothing. */
  avatar?: AgentState | false;
  icon?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={cx("flex flex-col items-center justify-center px-6 text-center", compact ? "py-8" : "py-14")}>
      {avatar ? (
        <AgentAvatar state={avatar} size={compact ? "sm" : "md"} />
      ) : (
        icon && <span className="text-ink-muted/60">{icon}</span>
      )}
      <p className={cx("font-semibold text-ink", compact ? "mt-2 text-sm" : "mt-4 text-sm")}>{title}</p>
      {hint && <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-ink-muted">{hint}</p>}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={cx("skeleton rounded-md", className)} />;
}

export function SkeletonText({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div aria-hidden className={cx("space-y-2", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cx("h-3", i === lines - 1 ? "w-3/5" : "w-full")} />
      ))}
    </div>
  );
}

/** A KPI tile: label, big number, trend against the previous window. */
export function Stat({
  label,
  value,
  delta,
  deltaGoodDirection = "up",
  hint,
  icon,
  loading = false,
  accent = false,
}: {
  label: string;
  value: ReactNode;
  delta?: number | null;
  deltaGoodDirection?: "up" | "down";
  hint?: ReactNode;
  icon?: ReactNode;
  loading?: boolean;
  /** Draws the eye, e.g. "on the line right now" when non-zero. */
  accent?: boolean;
}) {
  return (
    <Card className={cx("relative overflow-hidden px-4 py-4", accent && "border-brand/40")}>
      {accent && <span className="absolute inset-x-0 top-0 h-0.5 bg-brand" aria-hidden />}
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-ink-muted">{label}</p>
        {icon && <span className={accent ? "text-brand" : "text-ink-muted/70"}>{icon}</span>}
      </div>
      {loading ? (
        <Skeleton className="mt-3 h-7 w-20" />
      ) : (
        <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="tnum text-2xl font-semibold leading-none tracking-tight text-ink">{value}</span>
          {delta !== undefined && <DeltaBadge value={delta} goodDirection={deltaGoodDirection} />}
        </div>
      )}
      {hint && <p className="mt-2 text-xs text-ink-muted">{hint}</p>}
    </Card>
  );
}

/** Monospaced text in a scrollable well — tool arguments, results, JSON. */
export function CodeBlock({
  children,
  copyLabel,
  className = "",
}: {
  children: string;
  /** Adds a copy button; the label names what was copied in the toast. */
  copyLabel?: string;
  className?: string;
}) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(children);
      toast.success(`${copyLabel} copied`);
    } catch {
      toast.error("Couldn't copy", "The browser blocked clipboard access.");
    }
  };
  return (
    <div className="relative">
      <pre
        className={cx(
          "max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-subtle/60 px-3 py-2 font-mono text-2xs leading-relaxed text-ink-secondary",
          copyLabel && "pr-10",
          className,
        )}
      >
        {children}
      </pre>
      {copyLabel && (
        <IconButton
          label={`Copy ${copyLabel.toLowerCase()}`}
          icon={<IconCopy size={13} />}
          size="sm"
          tooltip={false}
          onClick={copy}
          className="absolute right-1 top-1 !h-7 !w-7"
        />
      )}
    </div>
  );
}

/** Small key/value figure used in ledgers (cost, tokens). */
export function Figure({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div>
      <p className="text-2xs font-medium text-ink-muted">{label}</p>
      <p className="tnum mt-0.5 text-sm font-semibold text-ink">{value}</p>
    </div>
  );
}

