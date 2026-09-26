/**
 * Command palette (⌘K / Ctrl+K, or "/"). Jump to any page or campaign, or
 * run an action, without leaving the keyboard.
 *
 * ARIA combobox pattern: the input owns the listbox and moves a virtual
 * cursor with aria-activedescendant, so focus never leaves the input.
 */

import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, m } from "framer-motion";
import { api, type Campaign } from "../api";
import { canManageTeam, useAuth, useSignOut } from "../auth";
import { useTheme } from "../theme";
import { T } from "../motion";
import { NAV_ITEMS } from "./shell/nav";
import {
  IconCampaign,
  IconKeyboard,
  IconLogout,
  IconMoon,
  IconPhone,
  IconPlug,
  IconPlus,
  IconSearch,
  IconSun,
  IconUsers,
} from "./icons";
import { Kbd } from "./ui";

interface Command {
  id: string;
  label: string;
  hint: string;
  icon: ReactNode;
  group: string;
  run: () => void;
}

export default function CommandPalette({
  open,
  onClose,
  onShowShortcuts,
}: {
  open: boolean;
  onClose: () => void;
  onShowShortcuts: () => void;
}) {
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const auth = useAuth();
  const signOut = useSignOut();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    const previous = document.activeElement as HTMLElement | null;
    requestAnimationFrame(() => inputRef.current?.focus());
    // Refetch each time: campaigns change, and this is cheap.
    api.campaigns().then(setCampaigns).catch(() => setCampaigns([]));
    return () => previous?.focus?.();
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const go = (to: string) => () => navigate(to);
    const all: Command[] = [
      ...NAV_ITEMS.map((item) => ({
        id: `page-${item.to}`,
        label: item.label,
        hint: item.hint,
        icon: item.icon(15),
        group: "Go to",
        run: go(item.to),
      })),
      { id: "a-new", label: "New campaign", hint: "Start from scratch", icon: <IconPlus size={15} />, group: "Actions", run: go("/app/campaigns/new") },
      { id: "a-call", label: "Place a test call", hint: "Ring your own phone", icon: <IconPhone size={15} />, group: "Actions", run: go("/app/test-lab/phone") },
      { id: "a-app", label: "Connect an app", hint: "Give the agent tools over MCP", icon: <IconPlug size={15} />, group: "Actions", run: go("/app/settings?connect=1") },
      ...(auth.registration !== null && canManageTeam(auth.user)
        ? [{ id: "a-invite", label: "Invite a teammate", hint: "Team and invites", icon: <IconUsers size={15} />, group: "Actions", run: go("/app/settings?tab=team") }]
        : []),
      {
        id: "a-theme",
        label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        hint: "Appearance",
        icon: theme === "dark" ? <IconSun size={15} /> : <IconMoon size={15} />,
        group: "Actions",
        run: toggle,
      },
      { id: "a-keys", label: "Keyboard shortcuts", hint: "?", icon: <IconKeyboard size={15} />, group: "Actions", run: onShowShortcuts },
      ...(auth.phase === "signed-in"
        ? [{ id: "a-out", label: "Sign out", hint: "End this session", icon: <IconLogout size={15} />, group: "Actions", run: signOut }]
        : []),
      ...(campaigns ?? []).map((c) => ({
        id: `c-${c.id}`,
        label: c.name,
        hint: `${c.status} · ${c.total_contacts} contacts`,
        icon: <IconCampaign size={15} />,
        group: "Campaigns",
        run: go(`/app/campaigns/${c.id}`),
      })),
    ];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter((c) => c.label.toLowerCase().includes(q) || c.hint.toLowerCase().includes(q));
  }, [campaigns, query, navigate, theme, toggle, onShowShortcuts, auth.phase, auth.registration, auth.user, signOut]);

  const grouped = useMemo(() => {
    const groups = new Map<string, Command[]>();
    commands.forEach((c) => groups.set(c.group, [...(groups.get(c.group) ?? []), c]));
    return [...groups.entries()];
  }, [commands]);

  // Keep the highlighted row in view as the cursor moves.
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const execute = (command: Command) => {
    onClose();
    command.run();
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <m.div
          key="palette"
          className="fixed inset-0 z-[65] flex items-start justify-center px-4 pt-[12vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={T.fast}
        >
          <div className="absolute inset-0 bg-[var(--overlay)] backdrop-blur-[2px]" onClick={onClose} />
          <m.div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={T.base}
            className="relative w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-raised elev-3"
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <IconSearch size={16} className="shrink-0 text-ink-muted" />
              <input
                ref={inputRef}
                value={query}
                role="combobox"
                aria-expanded="true"
                aria-controls={listId}
                aria-activedescendant={commands[active] ? `${listId}-${active}` : undefined}
                aria-autocomplete="list"
                placeholder="Search pages, campaigns and actions…"
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setActive((i) => Math.min(i + 1, commands.length - 1));
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setActive((i) => Math.max(i - 1, 0));
                  } else if (e.key === "Enter" && commands[active]) {
                    e.preventDefault();
                    execute(commands[active]);
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    onClose();
                  }
                }}
                className="h-12 w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-muted"
              />
              <Kbd>esc</Kbd>
            </div>

            <div ref={listRef} id={listId} role="listbox" aria-label="Results" className="max-h-[52vh] overflow-y-auto p-1.5">
              {commands.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-ink-muted">
                  Nothing matches “{query}”.
                </p>
              ) : (
                grouped.map(([group, items]) => (
                  <div key={group} role="group" aria-label={group} className="mb-1">
                    <p className="px-2.5 pb-1 pt-2 text-2xs font-medium uppercase tracking-wider text-ink-muted">
                      {group}
                    </p>
                    {items.map((command) => {
                      const index = commands.indexOf(command);
                      const selected = index === active;
                      return (
                        <div
                          key={command.id}
                          id={`${listId}-${index}`}
                          role="option"
                          aria-selected={selected}
                          data-index={index}
                          onMouseMove={() => setActive(index)}
                          onClick={() => execute(command)}
                          className={`flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                            selected ? "bg-subtle text-ink" : "text-ink-secondary"
                          }`}
                        >
                          <span className={selected ? "text-brand" : "text-ink-muted"}>{command.icon}</span>
                          <span className="flex-1 truncate font-medium">{command.label}</span>
                          <span className="hidden truncate text-xs text-ink-muted sm:inline">{command.hint}</span>
                        </div>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            <div className="hidden items-center gap-4 border-t border-line px-4 py-2.5 text-2xs text-ink-muted sm:flex">
              <span className="flex items-center gap-1.5"><Kbd>↑</Kbd><Kbd>↓</Kbd> move</span>
              <span className="flex items-center gap-1.5"><Kbd>↵</Kbd> open</span>
              <span className="flex items-center gap-1.5"><Kbd>?</Kbd> all shortcuts</span>
            </div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
