/**
 * Follow one call in real time (§1.2).
 *
 * Source of truth, in order of preference:
 *   1. `/api/events` — call.state / call.turn / call.whisper / call.tool /
 *      call.ended / call.extracted / call.failed, filtered by call_id;
 *   2. `GET /api/calls/{id}` — polled every few seconds while the socket is
 *      down (the backend saves the transcript after every turn), and fetched
 *      once whenever the socket comes back, to fill any gap.
 *
 * Phases only move forward: dialing → ringing → connected → wrapping → done,
 * or → failed from anywhere. Late or duplicated events can't rewind the UI.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  api,
  type CallDetail,
  type CallExtractedPayload,
  type CallStateName,
  type CallToolEvent,
  type LiveCallInfo,
  type LiveEvent,
  type TestCallResult,
} from "../../api";
import { eventStream } from "../../events";
import { useEventStream } from "../../hooks";
import type { AgentState } from "../AgentAvatar";
import { toolActivity } from "../mcp/toolText";
import { toolTurnFromLog, type DisplayTurn, type ToolActivity } from "../Transcript";

export type CallPhase = "dialing" | "ringing" | "connected" | "wrapping" | "done" | "failed";

const ORDER: Record<CallPhase, number> = { dialing: 0, ringing: 1, connected: 2, wrapping: 3, done: 4, failed: 5 };

export interface CallStream {
  phase: CallPhase;
  /** The last phase reached before failing — where the stepper shows the break. */
  failedFrom: CallPhase | null;
  liveState: CallStateName | null;
  /** While liveState is "working": the tool ids the agent paused to run. */
  workingTools: string[];
  turns: DisplayTurn[];
  whispers: DisplayTurn[];
  /** Tool rows (role "tool"), in the order they started. */
  tools: DisplayTurn[];
  startedAt: number;
  connectedAt: number | null;
  endedAt: number | null;
  extracted: CallExtractedPayload | null;
  result: TestCallResult | null;
  detail: CallDetail | null;
  error: string | null;
  contactName: string | null;
  isTest: boolean | null;
}

type Action =
  | { type: "event"; event: LiveEvent }
  | { type: "detail"; detail: CallDetail }
  | { type: "whisper"; text: string; at: string };

const ms = (iso: string | undefined | null) => (iso ? new Date(iso).getTime() : Date.now());

function advance(state: CallStream, to: CallPhase): CallStream {
  if (state.phase === "done" || state.phase === "failed") return state;
  if (to === "failed") return { ...state, phase: "failed", failedFrom: state.phase };
  return ORDER[to] > ORDER[state.phase] ? { ...state, phase: to } : state;
}

function markConnected(state: CallStream, at: string): CallStream {
  const next = advance(state, "connected");
  return next.connectedAt ? next : { ...next, connectedAt: ms(at) };
}

const sameTool = (a: ToolActivity, p: CallToolEvent) => a.phase === p.phase && a.server === p.server && a.tool === p.tool;

/**
 * "started" adds a row; "ok"/"error" completes the latest open row for the
 * same tool (or adds a finished one if its start was missed). Replayed
 * events are recognised and dropped.
 */
function applyToolEvent(rows: DisplayTurn[], p: CallToolEvent, at: string): DisplayTurn[] {
  const activity: ToolActivity = {
    phase: p.phase,
    server: p.server,
    tool: p.tool,
    status: p.status,
    arguments: p.arguments,
    durationMs: p.duration_ms,
    excerpt: p.excerpt,
    error: p.error,
  };
  const row: DisplayTurn = { key: `tool-${at}-${rows.length}`, role: "tool", text: toolActivity(p.tool), at, tool: activity };

  if (p.status === "started") {
    return rows.some((r) => r.at === at && r.tool && sameTool(r.tool, p)) ? rows : [...rows, row];
  }
  let open = -1;
  rows.forEach((r, i) => {
    if (r.tool?.status === "started" && sameTool(r.tool, p)) open = i;
  });
  if (open >= 0) return rows.map((r, i) => (i === open ? { ...r, tool: activity } : r));
  const replayed = rows.some(
    (r) => r.tool && sameTool(r.tool, p) && r.tool.status === p.status && r.tool.durationMs === p.duration_ms,
  );
  return replayed ? rows : [...rows, row];
}

function reduce(state: CallStream, action: Action): CallStream {
  if (action.type === "whisper") {
    const turn: DisplayTurn = { key: `w-${action.at}`, role: "whisper", text: action.text, at: action.at };
    return { ...state, whispers: [...state.whispers, turn] };
  }

  if (action.type === "detail") {
    const d = action.detail;
    let next: CallStream = {
      ...state,
      detail: d,
      contactName: state.contactName ?? d.contact_name,
      startedAt: d.started_at ? ms(d.started_at) : state.startedAt,
    };
    // The saved transcript is authoritative when it has at least as much.
    if (d.transcript.length >= next.turns.length) {
      next.turns = d.transcript.map((t, i) => ({
        key: `t-${i}`,
        role: t.role,
        text: t.text,
        latencyMs: t.latency_ms ?? null,
        at: t.started_at,
      }));
    }
    // Likewise the saved tool log, once it holds more finished calls than we
    // saw live. Rows still running after its last entry stay.
    const saved = d.tool_calls ?? [];
    if (saved.length > next.tools.filter((t) => t.tool?.status !== "started").length) {
      const last = Date.parse(saved[saved.length - 1].at);
      const running = next.tools.filter((t) => t.tool?.status === "started" && ms(t.at) > last);
      next.tools = [...saved.map(toolTurnFromLog), ...running];
    }
    if (d.transcript.length > 0 || d.status === "connected") next = markConnected(next, d.started_at);
    if (d.status === "completed") next = advance(next, d.outcome || d.disposition ? "done" : "wrapping");
    if (d.status === "failed") {
      next = advance(next, "failed");
      next.error = next.error ?? d.summary ?? "The call failed before it could finish.";
    }
    if ((next.phase === "done" || next.phase === "failed") && !next.endedAt) {
      next.endedAt = d.ended_at ? ms(d.ended_at) : Date.now();
    }
    return next;
  }

  const event = action.event;
  switch (event.type) {
    case "call.started":
      return {
        ...advance(state, "ringing"),
        contactName: event.payload.contact_name || state.contactName,
        isTest: event.payload.is_test ?? state.isTest,
      };
    case "call.connected":
      return markConnected(state, event.at);
    case "call.state": {
      const { state: liveState, tools } = event.payload;
      const live = { ...state, liveState, workingTools: liveState === "working" ? (tools ?? []) : [] };
      return liveState === "ended" ? advance(live, "wrapping") : markConnected(live, event.at);
    }
    case "call.tool":
      return { ...state, tools: applyToolEvent(state.tools, event.payload, event.at) };
    case "call.turn": {
      const p = event.payload;
      const last = state.turns[state.turns.length - 1];
      if (last && last.role === p.role && last.text === p.text) return state; // replayed duplicate
      const turn: DisplayTurn = {
        key: `t-${state.turns.length}`,
        role: p.role,
        text: p.text,
        latencyMs: p.latency_ms,
        at: p.at || event.at,
      };
      return { ...markConnected(state, event.at), turns: [...state.turns, turn] };
    }
    case "call.whisper": {
      // Ours already shows (added when the POST succeeded); only add others'.
      if (state.whispers.some((w) => w.text === event.payload.text)) return state;
      const turn: DisplayTurn = { key: `w-${event.at}`, role: "whisper", text: event.payload.text, at: event.at };
      return { ...state, whispers: [...state.whispers, turn] };
    }
    case "call.ended":
      return { ...advance(state, "wrapping"), endedAt: state.endedAt ?? ms(event.at) };
    case "call.extracted":
      return {
        ...advance(state, "done"),
        extracted: event.payload,
        result: event.payload.result ?? state.result,
        endedAt: state.endedAt ?? ms(event.at),
      };
    case "call.failed":
      return {
        ...advance(state, "failed"),
        error: event.payload.error || "The call failed.",
        endedAt: state.endedAt ?? ms(event.at),
      };
    default:
      return state;
  }
}

function initial(seed: LiveCallInfo | undefined, startedAt: number | undefined): CallStream {
  const seededTurns: DisplayTurn[] = Array.isArray(seed?.turns)
    ? seed.turns.map((t, i) => ({
        key: `t-${i}`,
        role: t.role,
        text: t.text,
        latencyMs: t.latency_ms ?? null,
        at: t.at ?? t.started_at ?? null,
      }))
    : [];
  const state = seed?.state as CallStateName | undefined;
  const connected =
    seededTurns.length > 0 || state === "speaking" || state === "listening" || state === "thinking" || state === "working";
  return {
    phase: state === "ended" ? "wrapping" : connected ? "connected" : "dialing",
    failedFrom: null,
    liveState: connected ? (state ?? null) : null,
    workingTools: [],
    turns: seededTurns,
    whispers: [],
    tools: [],
    startedAt: seed ? ms(seed.started_at) : (startedAt ?? Date.now()),
    connectedAt: connected && seed ? ms(seed.started_at) : null,
    endedAt: null,
    extracted: null,
    result: null,
    detail: null,
    error: null,
    contactName: seed?.contact_name ?? null,
    isTest: seed?.is_test ?? null,
  };
}

const POLL_MS = 3000;

export function useCallStream(callId: string, options: { seed?: LiveCallInfo; startedAt?: number } = {}) {
  const [state, dispatch] = useReducer(reduce, undefined, () => initial(options.seed, options.startedAt));
  const terminal = state.phase === "done" || state.phase === "failed";

  const onEvent = useCallback(
    (event: LiveEvent) => {
      if ("call_id" in event.payload && event.payload.call_id === callId) dispatch({ type: "event", event });
    },
    [callId],
  );
  const socket = useEventStream(onEvent);

  const fetchDetail = useCallback(async () => {
    try {
      dispatch({ type: "detail", detail: await api.call(callId) });
    } catch {
      /* not saved yet, or gone — the event stream still has us */
    }
  }, [callId]);

  // Replay anything that arrived before we subscribed, then read the saved row.
  useEffect(() => {
    eventStream
      .recent((e) => "call_id" in e.payload && e.payload.call_id === callId)
      .forEach((event) => dispatch({ type: "event", event }));
    void fetchDetail();
  }, [callId, fetchDetail]);

  // Socket down mid-call → poll the saved row. Socket back → one resync.
  const wasOpen = useRef(socket === "open");
  useEffect(() => {
    if (socket === "open") {
      if (!wasOpen.current) void fetchDetail();
      wasOpen.current = true;
      return;
    }
    wasOpen.current = false;
    if (terminal) return;
    const id = window.setInterval(() => void fetchDetail(), POLL_MS);
    return () => window.clearInterval(id);
  }, [socket, terminal, fetchDetail]);

  // When the outcome lands, read the full record (recording, follow-up
  // statuses, sentiment). Retry once: the row can trail the event slightly.
  useEffect(() => {
    if (state.phase !== "done") return;
    const first = window.setTimeout(() => void fetchDetail(), 500);
    const second = window.setTimeout(() => void fetchDetail(), 4000);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(second);
    };
  }, [state.phase, fetchDetail]);

  const addWhisper = useCallback((text: string) => {
    dispatch({ type: "whisper", text, at: new Date().toISOString() });
  }, []);

  return { ...state, transport: socket === "open" ? ("live" as const) : ("polling" as const), addWhisper };
}

export function avatarStateFor(phase: CallPhase, live: CallStateName | null): AgentState {
  if (phase === "failed") return "error";
  if (phase === "wrapping" || phase === "done") return "ended";
  if (phase === "dialing" || phase === "ringing") return "ringing";
  // Waiting on a tool looks like thinking: eyes up, dots rising.
  if (live === "working") return "thinking";
  if (live === "speaking" || live === "listening" || live === "thinking") return live;
  return "listening";
}
