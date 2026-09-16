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

  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fnRef
      .current()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err?.message || "Request failed");
          console.warn("[useAsync] fetch failed:", err);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload: useCallback(() => setNonce((n) => n + 1), []) };
}

/**
 * Live event feed with automatic reconnect.
 *
 * Reconnects with exponential backoff capped at 10s. Pauses reconnect
 * attempts while the tab is hidden to avoid wasting resources.
 */
export function useLiveFeed(onEvent?: (event: LiveEvent) => void) {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<LiveEvent[]>([]);

  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryDelay = 1000;
    let retryTimer: number | undefined;
    let closed = false;
    let connectAttempt = 0;

    const connect = () => {
      if (closed) return;
      // Don't reconnect while tab is hidden
      if (document.hidden) {
        retryTimer = window.setTimeout(connect, 2000);
        return;
      }

      connectAttempt++;
      try {
        socket = new WebSocket(liveFeedUrl());
      } catch {
        // WebSocket constructor can throw if URL is invalid
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 10_000);
        return;
      }

      socket.onopen = () => {
        setConnected(true);
        retryDelay = 1000;
        connectAttempt = 0;
      };

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as LiveEvent;
          setEvents((prev) => [event, ...prev].slice(0, 200));
          handlerRef.current?.(event);
        } catch (err) {
          console.warn("[LiveFeed] malformed frame:", err);
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (closed) return;
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 10_000);
      };

      socket.onerror = () => {
        // Let onclose handle reconnection
        try { socket?.close(); } catch { /* already closing */ }
      };
    };

    connect();

    // Resume connection when tab becomes visible
    const onVisibility = () => {
      if (!document.hidden && !connected && !closed) {
        window.clearTimeout(retryTimer);
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      closed = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearTimeout(retryTimer);
      try { socket?.close(); } catch { /* already closed */ }
    };
  }, []);

  const clear = useCallback(() => setEvents([]), []);
  return { connected, events, clear };
}

/** Poll a fetcher on an interval. Pauses while the tab is hidden.
 *  Tracks consecutive failures and surfaces stale state. */
export function usePolling<T>(fn: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [_stale, setStale] = useState(false);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const failCount = useRef(0);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      if (document.hidden) return;
      try {
        const result = await fnRef.current();
        if (!cancelled) {
          setData(result);
          setStale(false);
          failCount.current = 0;
        }
      } catch {
        failCount.current++;
        // Mark data as stale after 3 consecutive failures
        if (failCount.current >= 3 && !cancelled) {
          setStale(true);
        }
      }
    };

    void tick();
    const id = window.setInterval(tick, intervalMs);

    // Resume polling immediately when tab becomes visible
    const onVisibility = () => {
      if (!document.hidden && !cancelled) void tick();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs]);

  return data;
}
