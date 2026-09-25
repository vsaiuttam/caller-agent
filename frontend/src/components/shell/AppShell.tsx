/**
 * The console frame: collapsible sidebar (a drawer on phones), a top bar
 * with breadcrumbs, search, system health, theme and account, and the
 * global keyboard shortcuts.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth";
import { BRAND } from "../../brand";
import { useHealth, useLiveCalls, useStats, useStreamStatus } from "../../data";
import { useLocalStorage } from "../../hooks";
import { useTheme } from "../../theme";
import CommandPalette from "../CommandPalette";
import { Logo, LogoMark } from "../Logo";
import { MOD_KEY, ShortcutsDialog } from "../ShortcutsDialog";
import {
  IconCheck,
  IconChevronRight,
  IconClose,
  IconExternal,
  IconHelp,
  IconKeyboard,
  IconLock,
  IconLogout,
  IconMenu,
  IconMoon,
  IconSearch,
  IconSidebar,
  IconSun,
  IconUser,
} from "../icons";
import { Drawer, IconButton, Kbd, Popover, Tooltip, cx } from "../ui";
import { NAV_GROUPS, NAV_ITEMS, crumbsFor, type NavItem } from "./nav";

// ---------------------------------------------------------------------------
// Breadcrumb override — detail pages name their last crumb (a campaign's name)
// ---------------------------------------------------------------------------

const CrumbContext = createContext<(label: string | null) => void>(() => {});

export function useCrumb(label: string | null | undefined) {
  const set = useContext(CrumbContext);
  useEffect(() => {
    set(label ?? null);
    return () => set(null);
  }, [label, set]);
}

// ---------------------------------------------------------------------------

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useLocalStorage("samvaad.sidebar.collapsed", false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [crumb, setCrumb] = useState<string | null>(null);

  useEffect(() => setMobileOpen(false), [location.pathname]);

  const toggleCollapsed = useCallback(() => setCollapsed(!collapsed), [collapsed, setCollapsed]);

  // Global shortcuts. Ignored while typing or while a dialog is open.
  useEffect(() => {
    let awaitingG = false;
    let gTimer: number | undefined;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (document.querySelector('[aria-modal="true"]')) return;

      if (awaitingG) {
        awaitingG = false;
        window.clearTimeout(gTimer);
        const item = NAV_ITEMS.find((i) => i.key === e.key.toLowerCase());
        if (item) {
          e.preventDefault();
          navigate(item.to);
        }
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        setShortcutsOpen(true);
      } else if (e.key === "/") {
        e.preventDefault();
        setPaletteOpen(true);
      } else if (e.key === "[") {
        toggleCollapsed();
      } else if (e.key === "g") {
        awaitingG = true;
        gTimer = window.setTimeout(() => (awaitingG = false), 1200);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(gTimer);
    };
  }, [navigate, toggleCollapsed]);

  return (
    <CrumbContext.Provider value={setCrumb}>
      <a
        href="#main"
        className="sr-only z-[90] rounded-md bg-raised px-3 py-2 text-sm font-medium focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <div className="flex h-full">
        {/* Desktop sidebar */}
        <aside
          className={cx(
            "hidden shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200 ease-[var(--ease-out)] md:flex",
            collapsed ? "w-[60px]" : "w-60",
          )}
        >
          <div className={cx("flex h-14 shrink-0 items-center", collapsed ? "justify-center" : "px-4")}>
            <Link to="/dashboard" className="rounded-md" aria-label={`${BRAND.name} — overview`}>
              {collapsed ? (
                <LogoMark size={26} />
              ) : (
                <span className="flex items-center gap-2">
                  <Logo size={26} />
                  <span className="mt-0.5 text-xs text-ink-muted" lang="hi">
                    {BRAND.nativeName}
                  </span>
                </span>
              )}
            </Link>
          </div>
          <SidebarNav collapsed={collapsed} />
          <div className={cx("shrink-0 border-t border-line p-2", collapsed && "flex justify-center")}>
            {collapsed ? (
              <IconButton
                label="Expand sidebar"
                icon={<IconSidebar size={16} />}
                tooltipSide="right"
                onClick={toggleCollapsed}
              />
            ) : (
              <button
                type="button"
                onClick={toggleCollapsed}
                className="flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-xs text-ink-muted transition-colors hover:bg-subtle hover:text-ink"
              >
                <IconSidebar size={16} />
                <span className="flex-1 text-left">Collapse</span>
                <Kbd>[</Kbd>
              </button>
            )}
          </div>
        </aside>

        {/* Mobile nav drawer */}
        <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} side="left" width="max-w-[280px]" hideHeader label="Navigation">
          <div className="flex h-14 items-center justify-between px-4">
            <Logo size={26} />
            <IconButton label="Close navigation" icon={<IconClose size={16} />} tooltip={false} onClick={() => setMobileOpen(false)} />
          </div>
          <SidebarNav collapsed={false} />
        </Drawer>

        {/* Main column */}
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar
            crumb={crumb}
            onMenu={() => setMobileOpen(true)}
            onSearch={() => setPaletteOpen(true)}
            onShortcuts={() => setShortcutsOpen(true)}
          />
          <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden outline-none">
            <AuthBanner />
            {children}
          </main>
        </div>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onShowShortcuts={() => setShortcutsOpen(true)}
      />
      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </CrumbContext.Provider>
  );
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function SidebarNav({ collapsed }: { collapsed: boolean }) {
  const stats = useStats();
  const { calls } = useLiveCalls();

  const badgeFor = (item: NavItem): { count: number; live: boolean } | null => {
    if (item.badge === "review" && (stats?.pending_review ?? 0) > 0) return { count: stats!.pending_review, live: false };
    if (item.badge === "live" && calls.length > 0) return { count: calls.length, live: true };
    return null;
  };

  return (
    <nav aria-label="Main" className="flex-1 overflow-y-auto overflow-x-hidden px-2 pb-3">
      {NAV_GROUPS.map((group, gi) => (
        <div key={group.heading ?? gi}>
          {group.heading &&
            (collapsed ? (
              <div className="mx-2 my-3 h-px bg-line" aria-hidden />
            ) : (
              <p className="px-2.5 pb-1.5 pt-5 text-2xs font-medium uppercase tracking-wider text-ink-muted">
                {group.heading}
              </p>
            ))}
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const badge = badgeFor(item);
              const link = (
                <NavLink
                  to={item.to}
                  aria-label={collapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    cx(
                      "group relative flex h-8 items-center gap-2.5 rounded-md text-sm transition-colors duration-150",
                      collapsed ? "w-10 justify-center" : "px-2.5",
                      isActive
                        ? "bg-subtle font-medium text-ink"
                        : "text-ink-secondary hover:bg-subtle/70 hover:text-ink",
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className="absolute -left-2 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-brand" aria-hidden />
                      )}
                      <span className={cx("relative", isActive ? "text-brand" : "text-ink-muted group-hover:text-ink-secondary")}>
                        {item.icon(17)}
                        {collapsed && badge && (
                          <span className={cx("absolute -right-1 -top-1 h-2 w-2 rounded-full ring-2 ring-surface", badge.live ? "bg-good" : "bg-warning")} />
                        )}
                      </span>
                      {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
                      {!collapsed && badge && (
                        <span
                          className={cx(
                            "tnum inline-flex h-5 min-w-5 items-center justify-center gap-1 rounded-full px-1.5 text-2xs font-medium",
                            badge.live ? "bg-good/12 text-good" : "bg-warning/12 text-warning",
                          )}
                        >
                          {badge.live && <span className="live-dot h-1.5 w-1.5 rounded-full bg-good" />}
                          {badge.count}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              );
              return (
                <li key={item.to} className={collapsed ? "flex justify-center" : undefined}>
                  {collapsed ? (
                    <Tooltip content={badge ? `${item.label} · ${badge.count}` : item.label} side="right">
                      {link}
                    </Tooltip>
                  ) : (
                    link
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Top bar
// ---------------------------------------------------------------------------

function TopBar({
  crumb,
  onMenu,
  onSearch,
  onShortcuts,
}: {
  crumb: string | null;
  onMenu: () => void;
  onSearch: () => void;
  onShortcuts: () => void;
}) {
  const location = useLocation();
  const { theme, toggle } = useTheme();
  const auth = useAuth();
  const crumbs = crumbsFor(location.pathname, crumb);

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-line bg-plane/85 px-3 backdrop-blur-md sm:px-5">
      <IconButton label="Open navigation" icon={<IconMenu size={18} />} className="md:hidden" tooltip={false} onClick={onMenu} />
      <Link to="/dashboard" className="rounded-md md:hidden" aria-label={`${BRAND.name} — overview`}>
        <LogoMark size={24} />
      </Link>

      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex min-w-0 items-center gap-1.5 text-sm">
          {crumbs.map((c, i) => {
            const last = i === crumbs.length - 1;
            return (
              <li key={i} className={cx("flex min-w-0 items-center gap-1.5", !last && "hidden sm:flex")}>
                {c.to && !last ? (
                  <Link to={c.to} className="truncate rounded text-ink-muted transition-colors hover:text-ink">
                    {c.label}
                  </Link>
                ) : (
                  <span aria-current={last ? "page" : undefined} className="truncate font-medium text-ink">
                    {c.label}
                  </span>
                )}
                {!last && <IconChevronRight size={14} className="shrink-0 text-ink-muted/60" />}
              </li>
            );
          })}
        </ol>
      </nav>

      <button
        type="button"
        onClick={onSearch}
        className="hidden h-9 w-56 items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm text-ink-muted transition-colors hover:border-line-strong hover:text-ink-secondary lg:flex"
      >
        <IconSearch size={15} />
        <span className="flex-1 text-left">Search…</span>
        <span className="flex gap-0.5">
          <Kbd>{MOD_KEY}</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>
      <IconButton label="Search" icon={<IconSearch size={17} />} className="lg:hidden" onClick={onSearch} />

      <HealthPill />

      <IconButton
        label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        icon={theme === "dark" ? <IconSun size={17} /> : <IconMoon size={17} />}
        onClick={toggle}
      />

      {auth.phase === "signed-in" ? (
        <UserMenu onShortcuts={onShortcuts} onSignOut={auth.signOut} />
      ) : (
        <IconButton label="Keyboard shortcuts" icon={<IconHelp size={17} />} className="hidden sm:inline-flex" onClick={onShortcuts} />
      )}
    </header>
  );
}

// ---------------------------------------------------------------------------
// System health
// ---------------------------------------------------------------------------

const CHECK_LABELS: Record<string, string> = {
  database: "Database",
  model_provider: "Model provider",
  telephony: "Telephony",
  twilio: "Twilio account",
  sms: "SMS follow-ups",
  whatsapp: "WhatsApp follow-ups",
  speech_to_text: "Speech-to-text",
  text_to_speech: "Text-to-speech",
  calendar: "Calendar",
  records_api: "Records / CRM",
  webhook_signing: "Webhook signing",
};

function HealthPill() {
  const { health, error } = useHealth();
  const stream = useStreamStatus();
  const [open, setOpen] = useState(false);

  const status: { tone: "good" | "warning" | "critical" | "muted"; label: string; detail: string } = !health
    ? error
      ? { tone: "critical", label: "API unreachable", detail: error }
      : { tone: "muted", label: "Checking…", detail: "Asking the server what's connected." }
    : !health.ok
      ? { tone: "critical", label: "Degraded", detail: "The database isn't answering." }
      : !health.can_run_simulations
        ? { tone: "warning", label: "No model", detail: "No model provider key is set, so nothing can talk." }
        : !health.can_place_calls
          ? { tone: "warning", label: "Demo mode", detail: "Telephony is mocked — rehearsals work, real calls don't." }
          : { tone: "good", label: "Operational", detail: "Model provider and telephony are connected." };

  const dot = {
    good: "bg-good",
    warning: "bg-warning",
    critical: "bg-critical",
    muted: "bg-ink-muted/50",
  }[status.tone];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`System status: ${status.label}`}
        className="flex h-9 items-center gap-2 rounded-md border border-line bg-surface px-2.5 text-xs font-medium text-ink-secondary transition-colors hover:border-line-strong hover:text-ink"
      >
        <span className="relative flex h-2 w-2">
          {status.tone === "good" && <span className={cx("live-dot absolute inset-0 rounded-full opacity-60", dot)} />}
          <span className={cx("relative h-2 w-2 rounded-full", dot)} />
        </span>
        <span className="hidden sm:inline">{status.label}</span>
      </button>
      <Popover open={open} onClose={() => setOpen(false)} label="System status" className="w-72 p-1.5">
        <div className="px-2.5 pb-2 pt-1.5">
          <p className="text-sm font-semibold text-ink">{status.label}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{status.detail}</p>
        </div>
        {health && (
          <ul className="max-h-64 overflow-y-auto border-y border-line py-1.5">
            {Object.entries(CHECK_LABELS)
              .filter(([key]) => key in health.checks)
              .map(([key, label]) => (
                <li key={key} className="flex items-center justify-between px-2.5 py-1 text-xs">
                  <span className="text-ink-secondary">{label}</span>
                  {health.checks[key] ? (
                    <span className="flex items-center gap-1 text-good">
                      <IconCheck size={12} /> Live
                    </span>
                  ) : (
                    <span className="text-ink-muted">Off</span>
                  )}
                </li>
              ))}
          </ul>
        )}
        <div className="space-y-1 px-2.5 py-2 text-xs text-ink-muted">
          {health && (
            <p>
              Telephony: <span className="font-medium capitalize text-ink-secondary">{health.telephony_mode}</span>
              {health.provider_label && (
                <>
                  {" "}· Model: <span className="font-medium text-ink-secondary">{health.provider_label}</span>
                </>
              )}
            </p>
          )}
          <p className="flex items-center gap-1.5">
            <span className={cx("h-1.5 w-1.5 rounded-full", stream === "open" ? "bg-good" : "bg-warning")} />
            Live updates {stream === "open" ? "connected" : stream === "connecting" ? "connecting…" : "reconnecting…"}
          </p>
        </div>
        <Link
          to="/settings?tab=services"
          onClick={() => setOpen(false)}
          className="flex items-center justify-between rounded-lg px-2.5 py-2 text-xs font-medium text-ink transition-colors hover:bg-subtle"
        >
          Open integrations <IconExternal size={13} />
        </Link>
      </Popover>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Account
// ---------------------------------------------------------------------------

function UserMenu({ onShortcuts, onSignOut }: { onShortcuts: () => void; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const item =
    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm text-ink-secondary transition-colors hover:bg-subtle hover:text-ink";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Account"
        className="flex h-9 w-9 items-center justify-center rounded-full border border-line bg-subtle text-ink-secondary transition-colors hover:text-ink"
      >
        <IconUser size={16} />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} label="Account" className="w-60 p-1.5">
        <div className="flex items-center gap-2.5 px-2.5 py-2">
          <IconLock size={15} className="text-good" />
          <div>
            <p className="text-sm font-medium text-ink">Administrator</p>
            <p className="text-2xs text-ink-muted">Password-protected workspace</p>
          </div>
        </div>
        <div className="my-1 h-px bg-line" />
        <button type="button" className={item} onClick={() => { setOpen(false); onShortcuts(); }}>
          <IconKeyboard size={15} /> Keyboard shortcuts
        </button>
        <button type="button" className={item} onClick={() => { setOpen(false); onSignOut(); }}>
          <IconLogout size={15} /> Sign out
        </button>
      </Popover>
    </div>
  );
}

/** Shown when auth is off: honest about who can dial. */
function AuthBanner() {
  const auth = useAuth();
  const [dismissed, setDismissed] = useLocalStorage("samvaad.authBanner.dismissed", false);
  if (auth.phase !== "open" || dismissed) return null;
  return (
    <div className="flex items-center gap-3 border-b border-warning/25 bg-warning/8 px-4 py-2 text-xs text-ink-secondary sm:px-6 lg:px-8">
      <IconLock size={14} className="shrink-0 text-warning" />
      <p className="min-w-0 flex-1">
        <span className="font-medium text-ink">Anyone with this link can place calls</span> — set{" "}
        <code className="font-mono rounded bg-subtle px-1 py-0.5 text-2xs">ADMIN_PASSWORD</code> to lock it.
      </p>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="rounded-md p-1 text-ink-muted transition-colors hover:bg-subtle hover:text-ink"
      >
        <IconClose size={14} />
      </button>
    </div>
  );
}
