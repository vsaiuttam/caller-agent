import { useCallback, useEffect, useRef, useState } from "react";
import { liveFeedUrl, type LiveEvent } from "./api";

/** Fetch-on-mount with manual refetch, loading and error state. */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
): {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  // Keep the latest fn without making it a dependency — callers almost always
  // pass an inline arrow, which would otherwise refetch on every render.
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fnRef
      .current()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}

/**
 * Live event feed with automatic reconnect.
 *
 * Backoff is capped at 10s: an operator watching a call in progress needs the
 * stream back quickly, and the server-side cost of a reconnect is trivial.
 */
export function useLiveFeed(onEvent?: (event: LiveEvent) => void) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<LiveEvent[]>([]);

  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryDelay = 500;
    let retryTimer: number | undefined;
    let closed = false;

    const connect = () => {
      if (closed) return;
      socket = new WebSocket(liveFeedUrl());

      socket.onopen = () => {
        setConnected(true);
        retryDelay = 500;
      };

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as LiveEvent;
          // Cap the buffer — a long-running campaign would otherwise grow
          // this array until the tab runs out of memory.
          setEvents((prev) => [event, ...prev].slice(0, 200));
          handlerRef.current?.(event);
        } catch {
          /* ignore malformed frames */
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (closed) return;
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 10_000);
      };

      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  const clear = useCallback(() => setEvents([]), []);
  return { connected, events, clear };
}

/** Poll a fetcher on an interval. Pauses while the tab is hidden. */
export function usePolling<T>(fn: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      if (document.hidden) return;
      try {
        const result = await fnRef.current();
        if (!cancelled) setData(result);
      } catch {
        /* transient; next tick retries */
      }
    };

    void tick();
    const id = window.setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [intervalMs]);

  return data;
}
