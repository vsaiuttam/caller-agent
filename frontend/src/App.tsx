import type { ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import CommandPalette from "./components/CommandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import {
  IconBlock,
  IconCampaign,
  IconChip,
  IconDashboard,
  IconFlask,
  IconMic,
  IconMoon,
  IconPhone,
  IconReview,
  IconSearch,
  IconSparkle,
  IconSun,
} from "./components/icons";
import { Logo, Spinner } from "./components/ui";
import { useLiveFeed, usePolling } from "./hooks";
import { useTheme } from "./theme";
import Calls from "./pages/Calls";
import CampaignDetail from "./pages/CampaignDetail";
import Campaigns from "./pages/Campaigns";
import Dashboard from "./pages/Dashboard";
import LiveMic from "./pages/LiveMic";
import Models from "./pages/Models";
import NewCampaign from "./pages/NewCampaign";
import Simulator from "./pages/Simulator";
import Suppressions from "./pages/Suppressions";
import Templates from "./pages/Templates";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  badge?: "review";
}

const NAV_GROUPS: Array<{ heading: string; items: NavItem[] }> = [
  {
    heading: "Operate",
    items: [
      { to: "/dashboard", label: "Overview", icon: <IconDashboard /> },
      { to: "/calls", label: "Calls", icon: <IconPhone /> },
      { to: "/review", label: "Review", icon: <IconReview />, badge: "review" },
    ],
  },
  {
    heading: "Build",
    items: [
      { to: "/templates", label: "Templates", icon: <IconSparkle /> },
      { to: "/campaigns", label: "Campaigns", icon: <IconCampaign /> },
      { to: "/simulator", label: "Test calls", icon: <IconFlask /> },
      { to: "/live", label: "Live mic", icon: <IconMic /> },
    ],
  },
  {
    heading: "Configure",
    items: [
      { to: "/models", label: "Models", icon: <IconChip /> },
      { to: "/suppressions", label: "Do not call", icon: <IconBlock /> },
    ],
  },
];

const TITLES: Array<[RegExp, string]> = [
  [/^\/dashboard/, "Overview"],
  [/^\/templates/, "Templates"],
  [/^\/campaigns\/new/, "New campaign"],
  [/^\/campaigns\/[^/]+$/, "Campaign"],
  [/^\/campaigns/, "Campaigns"],
  [/^\/calls/, "Calls"],
  [/^\/review/, "Review queue"],
  [/^\/models/, "Models"],
  [/^\/simulator/, "Test calls"],
  [/^\/live/, "Live mic"],
  [/^\/suppressions/, "Do not call"],
];

export default function App() {
  const { connected } = useLiveFeed();
  const stats = usePolling(() => api.stats(), 20_000);
  const health = usePolling(() => api.health(), 120_000);
  const location = useLocation();
  const { theme, toggle: toggleTheme } = useTheme();

  const title =
    TITLES.find(([pattern]) => pattern.test(location.pathname))?.[1] ?? "CallerAgent";

  const telephonyLabel =
    health?.telephony_mode === "twilio"  ? "Twilio"
    : health?.telephony_mode === "telnyx" ? "Telnyx"
    : health?.telephony_mode === "livekit" ? "LiveKit"
    : "Mock";

  return (
    <div className="flex h-full">
      {/* ── Sidebar ──────────────────────────────────────────── */}
      <aside className="flex w-[220px] shrink-0 flex-col border-r border-[var(--surface-border)] bg-surface">
        {/* Brand */}
        <div className="flex items-center gap-2.5 px-5 py-4">
          <Logo size={26} />
          <span className="text-[13px] font-bold tracking-tight">CallerAgent</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-3 pb-2">
          {NAV_GROUPS.map((group) => (
            <div key={group.heading} className="mb-1">
              <p className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
                {group.heading}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `group relative flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13px] transition-colors duration-100 ${
                        isActive
                          ? "bg-brand/10 font-medium text-brand"
                          : "text-ink-secondary hover:bg-elevated hover:text-ink"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <div className="absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-r bg-brand" />
                        )}
                        <span className={isActive ? "text-brand" : "text-ink-muted group-hover:text-ink-secondary"}>
                          {item.icon}
                        </span>
                        <span className="flex-1">{item.label}</span>
                        {item.badge === "review" &&
                          (stats?.pending_review ?? 0) > 0 && (
                            <span className="tnum rounded-md bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning">
                              {stats!.pending_review}
                            </span>
                          )}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Bottom */}
        <div className="space-y-2 border-t border-[var(--surface-border)] px-4 py-3">
          <button
            type="button"
            onClick={() => {
              document.documentElement.classList.add("theme-transitioning");
              toggleTheme();
              setTimeout(() => document.documentElement.classList.remove("theme-transitioning"), 350);
            }}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-[7px] text-[13px] text-ink-secondary transition-colors hover:bg-elevated hover:text-ink"
          >
            {theme === "dark" ? <IconSun size={15} /> : <IconMoon size={15} />}
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>

          {health && (
            <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 ${
              health.can_place_calls
                ? "border-good/10 bg-good/5"
                : "border-warning/10 bg-warning/5"
            }`}>
              <span className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                health.can_place_calls ? "bg-good live-dot" : "bg-warning"
              }`} />
              <p className="text-[11px] leading-relaxed text-ink-secondary">
                {health.can_place_calls ? (
                  <>
                    <span className="font-medium text-good">{telephonyLabel}</span>{" "}
                    {health.live.length}/{health.live.length + health.mocked.length} live
                  </>
                ) : (
                  <>
                    <span className="font-medium text-warning">Demo mode</span>{" "}
                    {health.mocked.length} pending
                  </>
                )}
              </p>
            </div>
          )}

          <div className="flex items-center gap-1.5 px-2.5 text-[11px]">
            {connected ? (
              <>
                <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-good" />
                <span className="text-ink-muted">Connected</span>
              </>
            ) : (
              <>
                <Spinner size={11} />
                <span className="text-ink-muted">Reconnecting</span>
              </>
            )}
          </div>
        </div>
      </aside>

      {/* ── Main ─────────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header bar */}
        <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-[var(--surface-border)] bg-surface px-6">
          <p className="truncate text-[13px] font-semibold tracking-tight">{title}</p>

          <div className="flex items-center gap-3">
            {stats && (
              <span className="hidden items-center gap-3 text-xs md:flex">
                <span className="tnum text-ink-secondary">
                  {stats.calls_today.toLocaleString()} <span className="text-ink-muted">calls</span>
                </span>
                <span className="text-[var(--surface-border)]">|</span>
                <span className="tnum text-ink-secondary">
                  ${stats.spend_usd.toFixed(2)} <span className="text-ink-muted">spend</span>
                </span>
              </span>
            )}
            <button
              type="button"
              onClick={() =>
                window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))
              }
              className="flex items-center gap-1.5 rounded-lg border border-[var(--surface-border)] bg-elevated px-2.5 py-1 text-xs text-ink-muted transition-colors hover:border-brand/20 hover:text-ink-secondary"
            >
              <IconSearch size={12} />
              <span className="hidden sm:inline">Search</span>
              <kbd className="rounded border border-[var(--surface-border)] px-1 py-px text-[10px]">
                Ctrl K
              </kbd>
            </button>
          </div>
        </header>

        {/* Page */}
        <main className="min-h-0 flex-1 overflow-y-auto bg-plane">
          <div className="h-full">
            <ErrorBoundary>
              <Routes location={location}>
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/templates" element={<Templates />} />
                <Route path="/campaigns" element={<Campaigns />} />
                <Route path="/campaigns/new" element={<NewCampaign />} />
                <Route path="/campaigns/:id" element={<CampaignDetail />} />
                <Route path="/calls" element={<Calls />} />
                <Route path="/review" element={<Calls reviewOnly />} />
                <Route path="/models" element={<Models />} />
                <Route path="/simulator" element={<Simulator />} />
                <Route path="/live" element={<LiveMic />} />
                <Route path="/suppressions" element={<Suppressions />} />
              </Routes>
            </ErrorBoundary>
          </div>
        </main>
      </div>

      <CommandPalette />
    </div>
  );
}
