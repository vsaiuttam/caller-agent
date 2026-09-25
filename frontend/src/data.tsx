/**
 * App-wide data that several screens read at once — polled once here instead
 * of once per component.
 *
 *   useHealth()     /api/health, every minute (what's wired up, auth, mocks)
 *   useLiveCalls()  /api/calls/live, every few seconds and on every call event
 *   useStats()      /api/stats, for the nav's review badge
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, type DashboardStats, type Health, type LiveCallInfo, type LiveEvent } from "./api";
import { useEventStream, usePolling } from "./hooks";
import type { StreamStatus } from "./events";

interface HealthValue {
  health: Health | null;
  error: string | null;
  reload: () => void;
}

interface LiveCallsValue {
  calls: LiveCallInfo[];
  /** False when the backend predates /api/calls/live. */
  supported: boolean;
  loaded: boolean;
  refresh: () => void;
}

const HealthContext = createContext<HealthValue>({ health: null, error: null, reload: () => {} });
const LiveCallsContext = createContext<LiveCallsValue>({
  calls: [],
  supported: true,
  loaded: false,
  refresh: () => {},
});
const StatsContext = createContext<DashboardStats | null>(null);
const StreamContext = createContext<StreamStatus>("closed");

const LIVE_POLL_MS = 5_000;
const LIVE_POLL_UNSUPPORTED_MS = 60_000;

export function DataProvider({ children }: { children: ReactNode }) {
  const health = usePolling(() => api.health(), 60_000);
  const stats = usePolling(() => api.stats(), 30_000);

  const [calls, setCalls] = useState<LiveCallInfo[]>([]);
  const [supported, setSupported] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const refreshTimer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const list = await api.liveCalls();
      setCalls(list);
      setSupported(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setSupported(false);
        setCalls([]);
      }
      // Other failures: keep what we had; the health pill reports the outage.
    } finally {
      setLoaded(true);
    }
  }, []);

  /** Coalesce a burst of events into one refetch. */
  const refreshSoon = useCallback(() => {
    window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => void refresh(), 350);
  }, [refresh]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(
      () => !document.hidden && void refresh(),
      supported ? LIVE_POLL_MS : LIVE_POLL_UNSUPPORTED_MS,
    );
    return () => window.clearInterval(id);
  }, [refresh, supported]);

  const stream = useEventStream((event: LiveEvent) => {
    switch (event.type) {
      case "call.state":
        setCalls((prev) =>
          prev.map((c) => (c.call_id === event.payload.call_id ? { ...c, state: event.payload.state } : c)),
        );
        break;
      case "call.turn":
        setCalls((prev) =>
          prev.map((c) =>
            c.call_id === event.payload.call_id && Array.isArray(c.turns)
              ? { ...c, turns: [...c.turns, event.payload] }
              : c,
          ),
        );
        break;
      case "call.started":
      case "call.connected":
      case "call.ended":
      case "call.failed":
      case "call.extracted":
        refreshSoon();
        break;
      default:
        break;
    }
  });

  const liveValue = useMemo(
    () => ({ calls, supported, loaded, refresh: () => void refresh() }),
    [calls, supported, loaded, refresh],
  );

  return (
    <HealthContext.Provider value={{ health: health.data, error: health.error, reload: health.reload }}>
      <StatsContext.Provider value={stats.data}>
        <StreamContext.Provider value={stream}>
          <LiveCallsContext.Provider value={liveValue}>{children}</LiveCallsContext.Provider>
        </StreamContext.Provider>
      </StatsContext.Provider>
    </HealthContext.Provider>
  );
}

export const useHealth = () => useContext(HealthContext);
export const useLiveCalls = () => useContext(LiveCallsContext);
export const useStats = () => useContext(StatsContext);
/** Status of the shared event socket. */
export const useStreamStatus = () => useContext(StreamContext);
