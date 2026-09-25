import { useCallback, useEffect, useRef, useState } from "react";
import type { LiveEvent } from "./api";
import { BRAND } from "./brand";
import { eventStream, type StreamStatus } from "./events";

/**
 * Fetch on mount and whenever `deps` change, with manual `reload`.
 *
 * A reload keeps the current data on screen (`refreshing` is true meanwhile)
 * so refreshing after a mutation never flashes a skeleton; a deps change
 * clears it, because the old data belongs to something else.
 */
export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
): {
  data: T | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  reload: () => void;
  setData: (value: T | null) => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const lastNonce = useRef(nonce);

  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    const isReload = nonce !== lastNonce.current;
    lastNonce.current = nonce;
    if (isReload) setRefreshing(true);
    else {
      setData(null);
      setLoading(true);
    }
    setError(null);
    fnRef
      .current()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err?.message || "Request failed");
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return {
    data,
    loading,
    refreshing,
    error,
    reload: useCallback(() => setNonce((n) => n + 1), []),
    setData,
  };
}

/**
 * Poll a fetcher on an interval. Pauses while the tab is hidden and fetches
 * immediately when it comes back. Keeps the last good data through failures.
 */
export function usePolling<T>(fn: () => Promise<T>, intervalMs: number, enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const tickRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    const tick = async () => {
      if (document.hidden) return;
      try {
        const result = await fnRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message || "Request failed");
      }
    };
    tickRef.current = () => void tick();

    void tick();
    const id = window.setInterval(tick, intervalMs);
    const onVisibility = () => {
      if (!document.hidden && !cancelled) void tick();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, enabled]);

  const reload = useCallback(() => tickRef.current(), []);
  return { data, error, reload };
}

/** Subscribe to the shared /api/events socket. Returns its status. */
export function useEventStream(onEvent?: (event: LiveEvent) => void): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>(eventStream.status);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    const offStatus = eventStream.onStatus(setStatus);
    const off = eventStream.subscribe((event) => handlerRef.current?.(event));
    setStatus(eventStream.status);
    return () => {
      off();
      offStatus();
    };
  }, []);

  return status;
}

/** The current time, re-rendering every `intervalMs` while `active`. */
export function useNow(intervalMs = 1000, active = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs, active]);
  return now;
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/** State mirrored to localStorage. Falls back to memory when storage is blocked. */
export function useLocalStorage<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* private mode */
      }
    },
    [key],
  );
  return [value, set];
}

export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = `${title} · ${BRAND.name}`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
