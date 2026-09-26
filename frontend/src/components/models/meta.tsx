/**
 * Shared bits for model providers: the letter marks that stand in for logos
 * (we never ship other brands' artwork), status wording, and price display.
 */

import type { Estimate, EstimateComponent, Provider, ProviderModel, ProviderStatus, SpeedTier } from "../../api";
import { formatUsd } from "../../format";
import type { Tone } from "../ui";
import { cx } from "../ui";

/** Two characters per preset. Anything unknown falls back to its label's initials. */
const MARKS: Record<string, string> = {
  openai: "OA",
  anthropic: "An",
  gemini: "Ge",
  sarvam: "Sa",
  groq: "Gq",
  openrouter: "OR",
  deepseek: "DS",
  mistral: "Mi",
  together: "To",
  fireworks: "Fw",
  xai: "xA",
  nvidia: "NV",
  azure_openai: "Az",
  openai_compatible: "{ }",
};

export function markFor(kind: string, label?: string): string {
  if (MARKS[kind]) return MARKS[kind];
  const words = (label || kind).replace(/[_-]/g, " ").trim().split(/\s+/);
  return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).replace(/^./, (c) => c.toUpperCase());
}

export function ProviderMark({
  kind,
  label,
  size = "md",
  className = "",
}: {
  kind: string;
  label?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const box = size === "sm" ? "h-7 w-7 text-[10px] rounded-md" : size === "lg" ? "h-11 w-11 text-sm rounded-lg" : "h-9 w-9 text-xs rounded-lg";
  return (
    <span
      aria-hidden
      className={cx(
        "flex shrink-0 select-none items-center justify-center border border-line bg-subtle font-mono font-semibold tracking-tight text-ink-secondary",
        box,
        className,
      )}
    >
      {markFor(kind, label)}
    </span>
  );
}

export const STATUS_META: Record<ProviderStatus, { label: string; tone: Tone; dot: string }> = {
  ok: { label: "Working", tone: "good", dot: "bg-good" },
  untested: { label: "Not tested", tone: "neutral", dot: "bg-ink-muted/60" },
  error: { label: "Failing", tone: "critical", dot: "bg-critical" },
};

export const SPEED_LABEL: Record<SpeedTier, string> = {
  fastest: "Fastest",
  fast: "Fast",
  balanced: "Balanced",
  deliberate: "Deliberate",
};

export const speedLabel = (speed: ProviderModel["speed"]) =>
  speed ? (SPEED_LABEL[speed as SpeedTier] ?? String(speed).replace(/^./, (c) => c.toUpperCase())) : "—";

/** "$0.30" per 1M tokens; "Not set" when the price isn't known (never $0). */
export function perMillion(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not set";
  return value < 0.1 && value > 0 ? formatUsd(value, 3) : formatUsd(value, 2);
}

/** Money for an estimate: small values keep more digits so they don't read as $0.00. */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Unknown";
  if (value === 0) return "$0";
  if (value < 0.01) return formatUsd(value, 4);
  if (value < 1) return formatUsd(value, 3);
  return formatUsd(value, 2);
}

/** What a model is good at, from its speed, price and tool support. */
export function bestFor(model: ProviderModel): string {
  const tier = model.speed as SpeedTier | undefined;
  const cheap = model.output_per_mtok !== null && model.output_per_mtok <= 1;
  if (tier === "fastest" || tier === "fast") return model.supports_tools ? "Live calls with tools" : "Live calls";
  if (tier === "deliberate") return "Post-call extraction";
  if (cheap) return "High-volume campaigns";
  if (model.roles.includes("extraction") && !model.roles.includes("conversation")) return "Post-call extraction";
  return "General use";
}

export const COMPONENTS: Array<{ key: EstimateComponent; label: string; hint: string }> = [
  { key: "llm", label: "Conversation", hint: "The model on the call" },
  { key: "extraction", label: "Extraction", hint: "Reading the transcript afterwards" },
  { key: "stt", label: "Speech-to-text", hint: "Hearing the person" },
  { key: "tts", label: "Text-to-speech", hint: "The agent's voice" },
  { key: "telephony", label: "Telephony", hint: "Carrier minutes" },
];

export const SERIES_BG = ["bg-series-1", "bg-series-2", "bg-series-3", "bg-series-4", "bg-series-5"];

export const isUnknown = (estimate: Estimate, key: string) =>
  estimate.unknown.includes(key) || estimate.per_call[key as EstimateComponent] === null;

/** Env rows can't be edited or deleted in the app; they come from the server's environment. */
export const isEnvRow = (p: Provider) => p.source === "env" || p.id.startsWith("env:");
