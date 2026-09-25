/**
 * One WebSocket to /api/events for the whole tab.
 *
 * Every screen that wants live updates — the health pill, the live-calls
 * list, a call console — subscribes here instead of opening its own socket.
 * The socket opens with the first subscriber, closes a few seconds after the
 * last one leaves, and reconnects with jittered exponential backoff.
 *
 * Recent events are kept in a small buffer so a console that mounts a beat
 * after its call started (the POST answers, React renders, then subscribes)
 * can replay what it missed instead of showing a hole at the top.
 */

import { notifyUnauthorized, onTokenChange } from "./authStore";
import { liveFeedUrl, type LiveEvent } from "./api";

export type StreamStatus = "connecting" | "open" | "closed";

type Listener = (event: LiveEvent) => void;

const BUFFER_SIZE = 300;
const MAX_DELAY = 15_000;
const IDLE_CLOSE_MS = 5_000;
/** Close code the backend uses for a missing/expired token (§1.6). */
const UNAUTHORIZED = 4401;

class EventStream {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(status: StreamStatus) => void>();
  private buffer: LiveEvent[] = [];
  private delay = 1000;
  private retryTimer: number | undefined;
  private idleTimer: number | undefined;
  private blocked = false; // after a 4401, wait for a new token
  status: StreamStatus = "closed";

  constructor() {
    onTokenChange(() => {
      this.blocked = false;
      this.restart();
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && this.status === "closed" && this.listeners.size) {
        window.clearTimeout(this.retryTimer);
        this.connect();
      }
    });
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    window.clearTimeout(this.idleTimer);
    if (!this.socket) this.connect();
    return () => {
      this.listeners.delete(fn);
      if (!this.listeners.size) {
        this.idleTimer = window.setTimeout(() => this.close(), IDLE_CLOSE_MS);
      }
    };
  }

  onStatus(fn: (status: StreamStatus) => void): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  /** Events already received that match, oldest first. */
  recent(match: (event: LiveEvent) => boolean): LiveEvent[] {
    return this.buffer.filter(match);
  }

  private setStatus(status: StreamStatus) {
    if (this.status === status) return;
    this.status = status;
    this.statusListeners.forEach((fn) => fn(status));
  }

  private connect() {
    if (this.blocked || !this.listeners.size) return;
    // Don't burn reconnects in a background tab; visibilitychange resumes.
    if (document.hidden && this.status === "closed" && this.socket === null && this.delay > 1000) {
      return;
    }

    this.setStatus("connecting");
    let socket: WebSocket;
    try {
      socket = new WebSocket(liveFeedUrl());
    } catch {
      this.scheduleRetry();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.delay = 1000;
      this.setStatus("open");
    };

    socket.onmessage = (message: MessageEvent<string>) => {
      let event: LiveEvent;
      try {
        event = JSON.parse(message.data) as LiveEvent;
      } catch {
        console.warn("[events] malformed frame");
        return;
      }
      this.buffer.push(event);
      if (this.buffer.length > BUFFER_SIZE) this.buffer.splice(0, this.buffer.length - BUFFER_SIZE);
      this.listeners.forEach((fn) => {
        try {
          fn(event);
        } catch (err) {
          // One broken subscriber must not starve the others.
          console.error("[events] listener failed", err);
        }
      });
    };

    socket.onclose = (close) => {
      if (this.socket !== socket) return; // superseded by a restart
      this.socket = null;
      this.setStatus("closed");
      if (close.code === UNAUTHORIZED) {
        this.blocked = true;
        notifyUnauthorized();
        return;
      }
      this.scheduleRetry();
    };

    socket.onerror = () => {
      // onclose follows and owns the retry.
      try {
        socket.close();
      } catch {
        /* already closing */
      }
    };
  }

  private scheduleRetry() {
    if (!this.listeners.size) return;
    window.clearTimeout(this.retryTimer);
    const jitter = 0.8 + Math.random() * 0.4;
    this.retryTimer = window.setTimeout(() => this.connect(), this.delay * jitter);
    this.delay = Math.min(this.delay * 2, MAX_DELAY);
  }

  private close() {
    window.clearTimeout(this.retryTimer);
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      try {
        socket.close();
      } catch {
        /* already closed */
      }
    }
    this.setStatus("closed");
  }

  private restart() {
    this.close();
    this.delay = 1000;
    if (this.listeners.size) this.connect();
  }
}

export const eventStream = new EventStream();
