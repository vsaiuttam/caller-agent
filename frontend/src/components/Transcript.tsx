/**
 * Conversation rendering shared by every place a call is read: the live
 * console, the call log, simulated runs and the browser-mic rehearsal.
 *
 * Agent on the left with the mark, the person on the right in brand tint,
 * operator whispers as a centred note, and the tools the agent ran as
 * compact activity rows under the agent's side. Agent turns carry a latency
 * chip — the one number that decides whether a call feels human.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, m, useReducedMotion } from "framer-motion";
import { api, type JsonValue, type ToolCallLog, type ToolPhase } from "../api";
import { formatJson, formatMs, formatOffset, prettyText } from "../format";
import { T } from "../motion";
import { LogoMark } from "./Logo";
import { IconArrowDown, IconCheck, IconChevronDown, IconClose, IconCopy, IconDownload, IconWhisper, IconWrench } from "./icons";
import { toolActivity } from "./mcp/toolText";
import { Button, CodeBlock, Eyebrow, Tooltip, cx, toast } from "./ui";

/** One tool the agent ran, as the live feed and the call log report it. */
export interface ToolActivity {
  phase: ToolPhase;
  server: string;
  tool: string;
  status: "started" | "ok" | "error";
  arguments: JsonValue;
  durationMs: number | null;
  excerpt: string | null;
  error: string | null;
}

export interface DisplayTurn {
  key: string;
  role: "assistant" | "user" | "whisper" | "tool";
  text: string;
  latencyMs?: number | null;
  /** ISO time the turn started — rendered as an offset from the first turn. */
  at?: string | null;
  interrupted?: boolean;
  /** Still streaming in (browser mic). */
  partial?: boolean;
  /** Role "tool" only: what ran and how it went. */
  tool?: ToolActivity;
}

/** A saved `tool_calls` entry as a transcript row. */
export function toolTurnFromLog(entry: ToolCallLog, index: number): DisplayTurn {
  return {
    key: `tool-${index}`,
    role: "tool",
    text: toolActivity(entry.tool),
    at: entry.at,
    tool: {
      phase: entry.phase,
      server: entry.server,
      tool: entry.tool,
      status: entry.ok ? "ok" : "error",
      arguments: entry.arguments,
      durationMs: entry.duration_ms,
      excerpt: entry.excerpt,
      error: entry.error,
    },
  };
}

const spoken = (turn: DisplayTurn) => turn.role === "user" || turn.role === "assistant";
const timeOf = (turn: DisplayTurn) => (turn.at ? Date.parse(turn.at) : 0);

/**
 * Place tool rows among the turns (which are already in time order).
 *
 * An agent turn is recorded once it's finished but stamped with when it
 * began, so a tool the agent ran mid-reply looks *later* than the turn that
 * contains it. Each in-call tool therefore goes just before the agent turn
 * it happened in, or — while that reply is still coming — right after the
 * person's turn it answers. After-call tools go at the end.
 */
export function withTools(turns: DisplayTurn[], tools: DisplayTurn[]): DisplayTurn[] {
  const out = [...turns];
  for (const tool of tools) {
    if (tool.tool?.phase === "post_call") {
      out.push(tool);
      continue;
    }
    const at = timeOf(tool);
    let owner = -1;
    out.forEach((turn, i) => {
      if (spoken(turn) && timeOf(turn) <= at) owner = i;
    });
    if (owner >= 0 && out[owner].role === "assistant") {
      out.splice(owner, 0, tool);
      continue;
    }
    const next = out.findIndex((turn, i) => i > owner && spoken(turn));
    out.splice(next < 0 ? out.length : next, 0, tool);
  }
  return out;
}

export function latencyTone(ms: number): "good" | "warning" | "critical" {
  return ms < 800 ? "good" : ms < 1500 ? "warning" : "critical";
}

export function LatencyChip({ ms, label = "reply" }: { ms: number; label?: string }) {
  const tone = latencyTone(ms);
  return (
    <Tooltip content="From the person finishing to the agent's reply being ready. Under 0.8 s feels immediate.">
      <span
        tabIndex={0}
        className={cx(
          "tnum inline-flex h-[18px] items-center gap-1 rounded-full px-1.5 text-[10px] font-medium",
          tone === "good" && "bg-good/10 text-good",
          tone === "warning" && "bg-warning/12 text-warning",
          tone === "critical" && "bg-critical/10 text-critical",
        )}
      >
        <span className="h-1 w-1 rounded-full bg-current" aria-hidden />
        {formatMs(ms)}
        <span className="sr-only"> {label} latency</span>
      </span>
    </Tooltip>
  );
}

export function Bubble({
  turn,
  personName,
  startIso,
  animate = true,
}: {
  turn: DisplayTurn;
  personName: string;
  startIso?: string | null;
  animate?: boolean;
}) {
  const reduce = useReducedMotion();
  const motionProps =
    animate && !reduce
      ? { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: T.base }
      : {};

  if (turn.tool) {
    return (
      <m.li {...motionProps} className="flex pl-[38px]">
        <ToolRow activity={turn.tool} />
      </m.li>
    );
  }

  if (turn.role === "whisper") {
    return (
      <m.li {...motionProps} className="flex justify-center py-1">
        <span className="inline-flex max-w-[90%] items-start gap-2 rounded-lg border border-dashed border-info/40 bg-info/6 px-3 py-1.5 text-xs text-ink-secondary">
          <IconWhisper size={13} className="mt-0.5 shrink-0 text-info" />
          <span>
            <span className="font-medium text-info">Whisper to agent · </span>
            {turn.text}
          </span>
        </span>
      </m.li>
    );
  }

  const agent = turn.role === "assistant";
  const offset = turn.at && startIso ? formatOffset(turn.at, startIso) : null;

  return (
    <m.li {...motionProps} className={cx("flex gap-2.5", agent ? "justify-start" : "justify-end")}>
      {agent && (
        <span className="mt-5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-surface" aria-hidden>
          <LogoMark size={16} />
        </span>
      )}
      <div className={cx("flex min-w-0 max-w-[82%] flex-col", agent ? "items-start" : "items-end")}>
        <div className="mb-1 flex items-center gap-1.5 px-1 text-2xs text-ink-muted">
          <span className="font-medium text-ink-secondary">{agent ? "Agent" : personName}</span>
          {offset && <span className="tnum">{offset}</span>}
          {agent && turn.latencyMs != null && <LatencyChip ms={turn.latencyMs} />}
        </div>
        <div
          className={cx(
            "whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
            agent
              ? "rounded-tl-md border border-line bg-surface text-ink"
              : "rounded-tr-md bg-brand/12 text-ink",
            turn.partial && "border border-dashed border-line-strong bg-transparent text-ink-muted",
          )}
        >
          {turn.text || <span className="text-ink-muted">…</span>}
        </div>
        {turn.interrupted && (
          <span className="mt-1 px-1 text-2xs text-warning">Cut off — the rest was never heard</span>
        )}
      </div>
    </m.li>
  );
}

/**
 * "Checking availability… → ✓ 1.2 s", or "→ ✕ failed: reason". Opens to show
 * the arguments the agent sent and what came back.
 */
function ToolRow({ activity }: { activity: ToolActivity }) {
  const running = activity.status === "started";
  const hasArgs =
    activity.arguments !== null &&
    !(typeof activity.arguments === "object" && !Array.isArray(activity.arguments) && !Object.keys(activity.arguments).length);
  return (
    <details className="group min-w-0 max-w-[88%] rounded-lg border border-line bg-subtle/50 text-xs sm:max-w-[82%]">
      <summary className="flex cursor-pointer list-none items-start gap-2 rounded-lg px-2.5 py-1.5 [&::-webkit-details-marker]:hidden">
        <IconWrench size={12} className="mt-0.5 shrink-0 text-ink-muted" />
        <span className="min-w-0 flex-1 leading-relaxed">
          {activity.phase === "post_call" && <span className="font-medium text-info">After the call · </span>}
          <span className="font-medium text-ink-secondary">{toolActivity(activity.tool)}…</span>
          <span className="text-ink-muted"> · {activity.server}</span>
          <span className="text-ink-muted" aria-hidden>
            {" "}→{" "}
          </span>
          {running ? (
            <span className="inline-flex items-center gap-1 text-ink-muted">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-brand" aria-hidden />
              working
            </span>
          ) : activity.status === "ok" ? (
            <span className="tnum inline-flex items-center gap-0.5 font-medium text-good">
              <IconCheck size={11} />
              <span className="sr-only">succeeded in</span>
              {activity.durationMs != null ? formatMs(activity.durationMs) : "done"}
            </span>
          ) : (
            <span className="break-words font-medium text-critical">
              <IconClose size={11} className="-mt-px mr-0.5 inline" />
              failed{activity.error ? `: ${activity.error}` : ""}
            </span>
          )}
        </span>
        <IconChevronDown size={12} className="mt-0.5 shrink-0 text-ink-muted transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-2 border-t border-line px-2.5 py-2">
        <div>
          <Eyebrow className="mb-1">Asked for</Eyebrow>
          {hasArgs ? <CodeBlock>{formatJson(activity.arguments)}</CodeBlock> : <p className="text-ink-muted">No arguments.</p>}
        </div>
        <div>
          <Eyebrow className="mb-1">Got back</Eyebrow>
          {running ? (
            <p className="text-ink-muted">Still running…</p>
          ) : activity.excerpt ? (
            <CodeBlock>{prettyText(activity.excerpt)}</CodeBlock>
          ) : (
            <p className="text-ink-muted">{activity.error ?? "Nothing."}</p>
          )}
        </div>
      </div>
    </details>
  );
}

/** The "agent is composing" dots, sized like a short bubble so nothing jumps. */
function TypingBubble() {
  return (
    <m.li
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={T.fast}
      className="flex gap-2.5"
      aria-label="The agent is thinking"
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-surface" aria-hidden>
        <LogoMark size={16} />
      </span>
      <span className="flex h-10 items-center gap-1 rounded-2xl rounded-tl-md border border-line bg-surface px-4">
        {[0, 1, 2].map((i) => (
          <m.span
            key={i}
            className="h-1.5 w-1.5 rounded-full bg-ink-muted"
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.18 }}
          />
        ))}
      </span>
    </m.li>
  );
}

/** A static transcript (finished calls). */
export function TranscriptList({
  turns,
  personName,
  empty,
}: {
  turns: DisplayTurn[];
  personName: string;
  empty?: ReactNode;
}) {
  if (!turns.length) {
    return <p className="py-8 text-center text-xs text-ink-muted">{empty ?? "Nothing was said on this call."}</p>;
  }
  const startIso = turns.find((t) => t.at)?.at ?? null;
  return (
    <ol className="space-y-4" aria-label="Transcript">
      {turns.map((turn) => (
        <Bubble key={turn.key} turn={turn} personName={personName} startIso={startIso} animate={false} />
      ))}
    </ol>
  );
}

/**
 * A transcript that grows while you watch. Fixed height, so the page never
 * shifts as bubbles arrive. Sticks to the bottom while you're there; if you
 * scroll up to read, it stays put and offers "Jump to latest".
 */
export function LiveTranscript({
  turns,
  personName,
  typing = false,
  empty,
  className,
}: {
  turns: DisplayTurn[];
  personName: string;
  typing?: boolean;
  empty?: ReactNode;
  className?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const stuck = useRef(true);
  const seen = useRef(turns.length);
  const [unseen, setUnseen] = useState(0);
  const reduce = useReducedMotion();
  const startIso = turns.find((t) => t.at)?.at ?? null;

  const toBottom = useCallback(
    (smooth: boolean) => {
      const el = box.current;
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth && !reduce ? "smooth" : "auto" });
    },
    [reduce],
  );

  useLayoutEffect(() => {
    const added = turns.length - seen.current;
    seen.current = turns.length;
    if (stuck.current) toBottom(true);
    else if (added > 0) setUnseen((n) => n + added);
  }, [turns.length, toBottom]);

  // The typing bubble appearing counts as new content only if we're stuck.
  useEffect(() => {
    if (typing && stuck.current) toBottom(true);
  }, [typing, toBottom]);

  const onScroll = () => {
    const el = box.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 56;
    stuck.current = near;
    if (near) setUnseen(0);
  };

  return (
    <div className="relative">
      <div
        ref={box}
        onScroll={onScroll}
        className={cx("overflow-y-auto overscroll-contain px-4 py-5 sm:px-5", className ?? "h-[min(56vh,520px)]")}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Live transcript"
      >
        {turns.length === 0 && !typing ? (
          <div className="flex h-full items-center justify-center text-center text-xs text-ink-muted">{empty}</div>
        ) : (
          <ol className="space-y-4">
            {turns.map((turn) => (
              <Bubble key={turn.key} turn={turn} personName={personName} startIso={startIso} />
            ))}
            <AnimatePresence>{typing && <TypingBubble key="typing" />}</AnimatePresence>
          </ol>
        )}
      </div>

      <AnimatePresence>
        {unseen > 0 && (
          <m.button
            type="button"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={T.fast}
            onClick={() => {
              stuck.current = true;
              setUnseen(0);
              toBottom(true);
            }}
            className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-raised px-3 py-1.5 text-xs font-medium text-ink elev-2 transition-colors hover:bg-subtle"
          >
            <IconArrowDown size={13} />
            Jump to latest
            <span className="tnum rounded-full bg-brand px-1.5 text-2xs text-on-brand">{unseen}</span>
          </m.button>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Copy to clipboard, and download the server's TXT / JSON export. */
export function TranscriptActions({
  callId,
  turns,
  personName,
}: {
  callId: string;
  turns: DisplayTurn[];
  personName: string;
}) {
  const [downloading, setDownloading] = useState<"txt" | "json" | null>(null);
  const lines = turns.filter((t) => t.role !== "tool").length;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(transcriptText(turns, personName));
      toast.success("Transcript copied", `${lines} lines on your clipboard.`);
    } catch {
      toast.error("Couldn't copy", "The browser blocked clipboard access.");
    }
  };

  const download = async (format: "txt" | "json") => {
    setDownloading(format);
    try {
      await api.downloadTranscript(callId, format);
    } catch (err) {
      toast.error("Download failed", (err as Error).message);
    } finally {
      setDownloading(null);
    }
  };

  const disabled = lines === 0;
  return (
    <div className="flex items-center gap-1" role="group" aria-label="Transcript actions">
      <Button size="sm" variant="ghost" icon={<IconCopy size={13} />} onClick={copy} disabled={disabled}>
        Copy
      </Button>
      <Button
        size="sm"
        variant="ghost"
        icon={<IconDownload size={13} />}
        loading={downloading === "txt"}
        onClick={() => download("txt")}
        disabled={disabled}
        aria-label="Download transcript as text"
      >
        TXT
      </Button>
      <Button
        size="sm"
        variant="ghost"
        icon={<IconDownload size={13} />}
        loading={downloading === "json"}
        onClick={() => download("json")}
        disabled={disabled}
        aria-label="Download transcript as JSON"
      >
        JSON
      </Button>
    </div>
  );
}

/** Plain-text transcript for the clipboard, mirroring the server's TXT export (speech only). */
export function transcriptText(turns: DisplayTurn[], personName: string): string {
  const startIso = turns.find((t) => t.at)?.at ?? null;
  return turns
    .filter((t) => t.role !== "tool")
    .map((t) => {
      const who = t.role === "assistant" ? "Agent" : t.role === "user" ? personName : "Whisper";
      const clock = t.at && startIso ? `[${formatOffset(t.at, startIso)}] ` : "";
      return `${clock}${who}: ${t.text}`;
    })
    .join("\n");
}
