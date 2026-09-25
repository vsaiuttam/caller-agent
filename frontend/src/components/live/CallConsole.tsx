/**
 * Watch a call happen: the agent's face, a status stepper, the transcript
 * streaming in, a whisper line to the agent and an End call button — then
 * the outcome, scorecard and follow-ups the moment extraction finishes.
 *
 * Used by Test lab → "Call a phone" (a call you just placed) and by the Live
 * page (any call on the line, including campaign calls).
 */

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, m } from "framer-motion";
import { ApiError, api, type LiveCallInfo } from "../../api";
import { formatDuration, formatUsd } from "../../format";
import { useNow } from "../../hooks";
import { T } from "../../motion";
import { AgentAvatar } from "../AgentAvatar";
import { FigureCard, FollowupList, ResultFigures } from "../CallResult";
import { LatencyBars } from "../charts";
import {
  IconArrowRight,
  IconCheck,
  IconClock,
  IconClose,
  IconCoin,
  IconPhoneOff,
  IconRefresh,
  IconSend,
  IconShield,
  IconWhisper,
} from "../icons";
import { toolActivity, toolNameFromId } from "../mcp/toolText";
import OutcomeCard from "../OutcomeCard";
import { ScorecardResult } from "../Scorecard";
import { LiveTranscript, TranscriptActions, withTools, type DisplayTurn } from "../Transcript";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  DispositionBadge,
  FollowupBadge,
  IconButton,
  SentimentBadge,
  Skeleton,
  TestBadge,
  Tooltip,
  cx,
  toast,
} from "../ui";
import { avatarStateFor, useCallStream, type CallPhase, type CallStream } from "./useCallStream";

export type { CallPhase };

const STEPS: Array<{ phase: CallPhase; label: string }> = [
  { phase: "dialing", label: "Dialing" },
  { phase: "ringing", label: "Ringing" },
  { phase: "connected", label: "Connected" },
  { phase: "wrapping", label: "Wrapping up" },
  { phase: "done", label: "Done" },
];

export function CallConsole({
  callId,
  seed,
  startedAt,
  mode,
  onRetry,
  onClose,
  onPhaseChange,
}: {
  callId: string;
  seed?: LiveCallInfo;
  startedAt?: number;
  /** "test": a call you just placed. "watch": someone else's call, joined live. */
  mode: "test" | "watch";
  onRetry?: () => void;
  onClose?: () => void;
  onPhaseChange?: (phase: CallPhase) => void;
}) {
  const stream = useCallStream(callId, { seed, startedAt });
  const phaseListener = useRef(onPhaseChange);
  phaseListener.current = onPhaseChange;
  useEffect(() => phaseListener.current?.(stream.phase), [stream.phase]);
  const [ending, setEnding] = useState(false);
  const name = stream.contactName ?? "The person";
  const live = stream.phase === "dialing" || stream.phase === "ringing" || stream.phase === "connected";
  const terminal = stream.phase === "done" || stream.phase === "failed";

  const turns = useMemo<DisplayTurn[]>(
    () =>
      withTools(
        [...stream.turns, ...stream.whispers].sort(
          (a, b) => (a.at ? Date.parse(a.at) : 0) - (b.at ? Date.parse(b.at) : 0),
        ),
        stream.tools,
      ),
    [stream.turns, stream.whispers, stream.tools],
  );

  const hangup = async () => {
    setEnding(true);
    try {
      await api.hangup(callId);
      toast.info("Ending the call", "The agent will say goodbye and hang up.");
    } catch (err) {
      setEnding(false);
      toast.error(
        "Couldn't end the call",
        err instanceof ApiError && err.status === 404
          ? "It isn't live on this server any more."
          : (err as Error).message,
      );
    }
  };

  return (
    <div className="space-y-3">
      <Card className="overflow-hidden">
        <ConsoleHeader
          stream={stream}
          name={name}
          mode={mode}
          live={live}
          ending={ending}
          onEnd={hangup}
          onClose={onClose}
        />
        <div className="border-t border-line px-5 py-4">
          <StatusStepper
            phase={stream.phase}
            failedFrom={stream.failedFrom}
            working={stream.phase === "connected" && stream.liveState === "working"}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-subtle/40 px-5 py-2">
          <p className="text-xs font-medium text-ink-secondary">
            Transcript{" "}
            <span className="tnum font-normal text-ink-muted">
              · {stream.turns.length} {stream.turns.length === 1 ? "turn" : "turns"}
            </span>
          </p>
          <TranscriptActions callId={callId} turns={turns} personName={name} />
        </div>
        <div className="border-t border-line">
          <LiveTranscript
            turns={turns}
            personName={name}
            // A call that never connected has nothing to read; don't hold the space.
            className={stream.phase === "failed" && turns.length === 0 ? "h-28" : undefined}
            typing={stream.phase === "connected" && stream.liveState === "thinking"}
            empty={
              <span className="flex flex-col items-center gap-2">
                {stream.phase === "dialing" || stream.phase === "ringing"
                  ? `Waiting for ${name === "The person" ? "them" : name} to pick up…`
                  : stream.phase === "failed"
                    ? "Nothing was said."
                    : "The conversation will appear here as it happens."}
              </span>
            }
          />
        </div>

        <AnimatePresence initial={false}>
          {stream.phase === "connected" && !ending && (
            <m.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={T.base}
              className="border-t border-line"
            >
              <WhisperBox callId={callId} onSent={stream.addWhisper} />
            </m.div>
          )}
        </AnimatePresence>
      </Card>

      {stream.phase === "failed" && (
        <Callout
          tone="critical"
          title="The call didn't go through"
          action={
            onRetry && (
              <Button size="sm" variant="secondary" icon={<IconRefresh size={13} />} onClick={onRetry}>
                Try again
              </Button>
            )
          }
        >
          {stream.error}
        </Callout>
      )}

      {stream.phase === "wrapping" && <WrappingUp />}
      {stream.phase === "done" && <ConsoleOutcome stream={stream} callId={callId} name={name} />}
      {terminal && (
        <div className="flex justify-end">
          <Link
            to={`/calls?call=${callId}`}
            className="inline-flex items-center gap-1.5 rounded-md text-xs font-medium text-brand hover:underline"
          >
            Open in the call log <IconArrowRight size={13} />
          </Link>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function statusLine(stream: CallStream, name: string): string {
  switch (stream.phase) {
    case "dialing":
      return "Dialing…";
    case "ringing":
      return "Ringing — waiting for them to pick up";
    case "wrapping":
      return "Call ended — reading the transcript";
    case "done":
      return "Done — the outcome is ready";
    case "failed":
      return stream.error ? `The call failed — ${stream.error}` : "The call failed";
    default:
      if (stream.liveState === "working") {
        const doing = stream.workingTools.map((id) => toolActivity(toolNameFromId(id)).toLowerCase());
        return doing.length ? `Using a tool — ${doing.join(", ")}` : "Using a tool";
      }
      return stream.liveState === "speaking"
        ? "Agent is speaking"
        : stream.liveState === "thinking"
          ? "Thinking of a reply"
          : `Listening to ${name}`;
  }
}

function ConsoleHeader({
  stream,
  name,
  mode,
  live,
  ending,
  onEnd,
  onClose,
}: {
  stream: CallStream & { transport: "live" | "polling" };
  name: string;
  mode: "test" | "watch";
  live: boolean;
  ending: boolean;
  onEnd: () => void;
  onClose?: () => void;
}) {
  const terminal = stream.phase === "done" || stream.phase === "failed";
  const now = useNow(1000, !terminal);
  const from = stream.connectedAt ?? stream.startedAt;
  const elapsed = Math.max(0, ((stream.endedAt ?? now) - from) / 1000);
  const [confirming, setConfirming] = useState(false);
  const confirmTimer = useRef<number | undefined>(undefined);

  const clickEnd = () => {
    if (!confirming) {
      setConfirming(true);
      window.clearTimeout(confirmTimer.current);
      confirmTimer.current = window.setTimeout(() => setConfirming(false), 3500);
      return;
    }
    window.clearTimeout(confirmTimer.current);
    setConfirming(false);
    onEnd();
  };

  return (
    <div className="flex flex-wrap items-center gap-4 px-5 py-4">
      <AgentAvatar state={avatarStateFor(stream.phase, stream.liveState)} size="md" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="truncate text-lg font-semibold tracking-tight text-ink">{name}</h2>
          {mode === "test" || stream.isTest ? (
            <TestBadge />
          ) : (
            <Badge tone="info">Campaign call</Badge>
          )}
          {!terminal &&
            (stream.transport === "live" ? (
              <Badge tone="good" dot pulse>
                Live
              </Badge>
            ) : (
              <Tooltip content="The live connection dropped. Refreshing from the saved call every few seconds while it reconnects.">
                <span tabIndex={0}>
                  <Badge tone="warning" dot>
                    Reconnecting
                  </Badge>
                </span>
              </Tooltip>
            ))}
        </div>
        <p className="mt-1 text-sm text-ink-secondary" aria-live="polite">
          {statusLine(stream, name)}
        </p>
      </div>

      <div className="flex items-center gap-3">
        <div className="text-right">
          <p className="text-2xs font-medium text-ink-muted">{stream.connectedAt ? "Talk time" : "Elapsed"}</p>
          <p className="tnum text-xl font-semibold tabular-nums text-ink" aria-label={`${formatDuration(elapsed)} elapsed`}>
            {formatDuration(elapsed)}
          </p>
        </div>
        {live && (
          <Button
            variant={confirming ? "danger" : "secondary"}
            onClick={clickEnd}
            loading={ending}
            icon={<IconPhoneOff size={15} />}
            className={cx(!confirming && "text-critical")}
            aria-live="polite"
          >
            {ending ? "Ending…" : confirming ? "Click to confirm" : "End call"}
          </Button>
        )}
        {onClose && terminal && (
          <IconButton label="Close" icon={<IconClose size={16} />} onClick={onClose} />
        )}
      </div>
    </div>
  );
}

function StatusStepper({
  phase,
  failedFrom,
  working,
}: {
  phase: CallPhase;
  failedFrom: CallPhase | null;
  /** The agent paused to run a tool: the live step says so. */
  working: boolean;
}) {
  const reached = phase === "failed" ? STEPS.findIndex((s) => s.phase === failedFrom) : STEPS.findIndex((s) => s.phase === phase);
  return (
    <ol className="flex items-center" aria-label="Call progress">
      {STEPS.map((step, i) => {
        const failedHere = phase === "failed" && i === reached;
        const done = phase === "done" ? true : i < reached;
        const current = !done && !failedHere && i === reached;
        const last = i === STEPS.length - 1;
        return (
          <li
            key={step.phase}
            className={cx("flex items-center", !last && "flex-1")}
            aria-current={current ? "step" : undefined}
          >
            <span className="flex items-center gap-2">
              <span
                className={cx(
                  "relative flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold transition-colors duration-300",
                  done && "bg-brand text-on-brand",
                  current && "border-2 border-brand bg-surface",
                  failedHere && "bg-critical text-on-critical",
                  !done && !current && !failedHere && "border border-line-strong bg-surface text-ink-muted",
                )}
              >
                {done ? (
                  <IconCheck size={11} />
                ) : failedHere ? (
                  <IconClose size={11} />
                ) : current ? (
                  <span className="live-dot h-2 w-2 rounded-full bg-brand" />
                ) : null}
              </span>
              <span
                className={cx(
                  "whitespace-nowrap text-xs",
                  current || failedHere ? "font-medium text-ink" : done ? "text-ink-secondary" : "text-ink-muted",
                  !current && !failedHere && "hidden sm:inline",
                )}
              >
                {failedHere ? "Failed" : current && working && step.phase === "connected" ? "Using a tool" : step.label}
              </span>
            </span>
            {!last && (
              <span className="mx-2 h-0.5 flex-1 overflow-hidden rounded-full bg-line sm:mx-3" aria-hidden>
                <span
                  className="block h-full rounded-full bg-brand transition-[width] duration-500 ease-[var(--ease-out)]"
                  style={{ width: done ? "100%" : "0%" }}
                />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

const WHISPER_MAX = 500;

function WhisperBox({ callId, onSent }: { callId: string; onSent: (text: string) => void }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const trimmed = text.trim();

  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!trimmed || sending || trimmed.length > WHISPER_MAX) return;
    setSending(true);
    try {
      await api.whisper(callId, trimmed);
      onSent(trimmed);
      setText("");
      toast.success("Whisper sent", "The agent follows it from its next reply — the caller never hears it.");
    } catch (err) {
      toast.error(
        "Whisper not delivered",
        err instanceof ApiError && err.status === 404 ? "The call has already ended." : (err as Error).message,
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <form onSubmit={send} className="flex items-end gap-2 px-4 py-3 sm:px-5">
      <IconWhisper size={16} className="mb-2.5 shrink-0 text-info" />
      <label className="min-w-0 flex-1">
        <span className="sr-only">Whisper to the agent</span>
        <textarea
          value={text}
          rows={1}
          maxLength={WHISPER_MAX}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder="Whisper to the agent — e.g. “Offer the Tuesday 4 pm slot”"
          className="block max-h-28 min-h-9 w-full resize-none rounded-md border border-line-strong bg-surface px-3 py-2 text-sm leading-snug text-ink placeholder:text-ink-muted/80 focus:border-info focus:outline-none focus:ring-3 focus:ring-info/20"
        />
      </label>
      <span className={cx("tnum mb-2.5 hidden text-2xs sm:block", text.length > WHISPER_MAX * 0.9 ? "text-warning" : "text-ink-muted")}>
        {text.length}/{WHISPER_MAX}
      </span>
      <Button type="submit" variant="secondary" loading={sending} disabled={!trimmed} icon={<IconSend size={14} />}>
        Send
      </Button>
    </form>
  );
}

function WrappingUp() {
  return (
    <Card className="px-5 py-4" aria-busy="true">
      <p className="text-sm font-medium text-ink">Reading the transcript…</p>
      <p className="mt-0.5 text-xs text-ink-muted">
        The extraction model scores the call and writes the outcome after hang-up. A few seconds.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-20 rounded-xl" />
        ))}
      </div>
      <Skeleton className="mt-3 h-32 rounded-xl" />
    </Card>
  );
}

function ConsoleOutcome({ stream, callId, name }: { stream: CallStream; callId: string; name: string }) {
  const { result, detail, extracted } = stream;
  const latencies = stream.turns.filter((t) => t.latencyMs != null).map((t) => t.latencyMs as number);
  const sentiment = detail?.sentiment ?? extracted?.sentiment ?? result?.outcome.sentiment ?? null;
  // The saved row's figure when we have it, else what we timed ourselves.
  const talk =
    detail?.duration_seconds ??
    (stream.connectedAt && stream.endedAt ? Math.round((stream.endedAt - stream.connectedAt) / 1000) : null);

  const summaryCard = (
    <Card>
      <CardHeader
        title="How it went"
        subtitle={talk != null ? `${name} · ${formatDuration(talk)} talk time` : name}
        action={
          <>
            <SentimentBadge value={sentiment} />
            <DispositionBadge value={detail?.disposition ?? extracted?.disposition ?? result?.outcome.disposition ?? null} />
          </>
        }
      />
      <div className="space-y-4 px-5 py-4">
        {latencies.length > 1 && <LatencyBars values={latencies} />}
        {detail?.recording_url ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-ink-muted">Recording</p>
            <audio controls preload="none" className="w-full" src={api.recordingUrl(callId)}>
              Your browser can't play this recording.
            </audio>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">
            The recording appears in the call log once the carrier delivers it, usually within a minute.
          </p>
        )}
      </div>
    </Card>
  );

  if (result) {
    return (
      <m.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={T.slow} className="space-y-3">
        <ResultFigures result={result} />
        {summaryCard}
        {result.followups && <FollowupList followups={result.followups} />}
        <ScorecardResult scores={result.outcome.scores} qualification={result.qualification} />
        <OutcomeCard
          outcome={result.outcome}
          subtitle="Read off the real call by the extraction model."
          footnotes={[`On the call: ${result.conversation_model}`, `After: ${result.extraction_model}`]}
        />
      </m.div>
    );
  }

  if (detail?.outcome) {
    return (
      <m.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={T.slow} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <FigureCard label="Talk time" value={formatDuration(detail.duration_seconds)} hint="From pick-up to hang-up" icon={<IconClock size={15} />} />
          <FigureCard
            label="Cost of this call"
            value={formatUsd(detail.cost_usd, 4)}
            hint={`${detail.input_tokens.toLocaleString()} in · ${detail.output_tokens.toLocaleString()} out`}
            icon={<IconCoin size={15} />}
          />
          <FigureCard
            label="Review"
            value={detail.needs_human_review ? "Needed" : "Written"}
            hint={detail.needs_human_review ? detail.review_reason ?? "Held for a human" : "Outcome written automatically"}
            warn={detail.needs_human_review}
            icon={<IconShield size={15} />}
          />
        </div>
        {summaryCard}
        {(detail.sms_status || detail.whatsapp_status) && (
          <Card className="flex flex-wrap items-center gap-2 px-5 py-3">
            <span className="text-xs font-medium text-ink-muted">Follow-ups</span>
            {detail.sms_status && <FollowupBadge channel="sms" status={detail.sms_status} />}
            {detail.whatsapp_status && <FollowupBadge channel="whatsapp" status={detail.whatsapp_status} />}
          </Card>
        )}
        <ScorecardResult scores={detail.scores} qualification={detail.qualification} />
        <OutcomeCard outcome={detail.outcome} subtitle="Read off the call by the extraction model." />
      </m.div>
    );
  }

  if (extracted) {
    return (
      <Card>
        <CardHeader
          title="Outcome"
          subtitle={`Model cost ${formatUsd(extracted.cost_usd, 4)}`}
          action={<DispositionBadge value={extracted.disposition} />}
        />
        <p className="px-5 py-4 text-sm leading-relaxed text-ink">{extracted.summary}</p>
      </Card>
    );
  }

  return <WrappingUp />;
}
