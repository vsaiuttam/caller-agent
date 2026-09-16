/**
 * Command palette (Ctrl/Cmd-K).
 *
 * Once a workspace has more than a handful of campaigns, the nav stops being
 * how anyone actually gets around. This is: type a few letters of a campaign
 * name or a page and hit enter.
 *
 * Campaigns are loaded once when the palette first opens, not on every
 * keystroke — the list is small, and a request per character would be
 * needless load for a worse experience.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Campaign } from "../api";
import {
  IconBlock,
  IconCampaign,
  IconChip,
  IconDashboard,
  IconFlask,
  IconMic,
  IconPhone,
  IconReview,
  IconSearch,
  IconSparkle,
} from "./icons";

interface Command {
  id: string;
  label: string;
  hint: string;
  to: string;
  icon: React.ReactNode;
  group: string;
}

const PAGES: Command[] = [
  { id: "p-dash", label: "Overview", hint: "Dashboard", to: "/dashboard", icon: <IconDashboard size={15} />, group: "Go to" },
  { id: "p-tpl", label: "Templates", hint: "Prebuilt campaigns", to: "/templates", icon: <IconSparkle size={15} />, group: "Go to" },
  { id: "p-camp", label: "Campaigns", hint: "All campaigns", to: "/campaigns", icon: <IconCampaign size={15} />, group: "Go to" },
  { id: "p-calls", label: "Calls", hint: "Call history", to: "/calls", icon: <IconPhone size={15} />, group: "Go to" },
  { id: "p-review", label: "Review queue", hint: "Calls needing a human", to: "/review", icon: <IconReview size={15} />, group: "Go to" },
  { id: "p-models", label: "Models", hint: "Choose the LLM and see the cost", to: "/models", icon: <IconChip size={15} />, group: "Go to" },
  { id: "p-sim", label: "Test calls", hint: "Rehearse against a simulated person", to: "/simulator", icon: <IconFlask size={15} />, group: "Go to" },
  { id: "p-live", label: "Live mic", hint: "Take the call yourself", to: "/live", icon: <IconMic size={15} />, group: "Go to" },
  { id: "p-dnc", label: "Do not call", hint: "Suppression list", to: "/suppressions", icon: <IconBlock size={15} />, group: "Go to" },
  { id: "a-new", label: "New campaign", hint: "Start from scratch", to: "/campaigns/new", icon: <IconCampaign size={15} />, group: "Create" },
];

export default function CommandPalette() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((wasOpen) => !wasOpen);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActive(0);
      return;
    }
    inputRef.current?.focus();
    if (campaigns === null) {
      api
        .campaigns()
        .then(setCampaigns)
        // An empty list is the right degradation: pages still work, and a
        // toast about a background fetch nobody asked for is noise.
        .catch(() => setCampaigns([]));
    }
  }, [open, campaigns]);

  const commands = useMemo(() => {
    const all: Command[] = [
      ...PAGES,
      ...(campaigns ?? []).map((c) => ({
        id: `c-${c.id}`,
        label: c.name,
        hint: `${c.status} · ${c.total_contacts} contacts`,
        to: `/campaigns/${c.id}`,
        icon: <IconCampaign size={15} />,
        group: "Campaigns",
      })),
    ];

    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (c) =>
        c.label.toLowerCase().includes(q) || c.hint.toLowerCase().includes(q),
    );
  }, [campaigns, query]);

  const grouped = useMemo(() => {
    const groups = new Map<string, Command[]>();
    commands.forEach((c) => {
      const list = groups.get(c.group);
      if (list) list.push(c);
      else groups.set(c.group, [c]);
    });
    return [...groups.entries()];
  }, [commands]);

  const go = (command: Command) => {
    setOpen(false);
    navigate(command.to);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 backdrop-blur-sm px-4 pt-[12vh]"
      onClick={() => setOpen(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/10 bg-surface/95 shadow-2xl backdrop-blur-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-white/10 px-4 py-3">
          <span className="text-ink-muted">
            <IconSearch size={16} />
          </span>
          <input
            ref={inputRef}
            value={query}
            placeholder="Search campaigns and pages…"
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
                go(commands[active]);
              }
            }}
            className="w-full bg-transparent text-sm outline-none placeholder:text-ink-muted"
          />
          <kbd className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-ink-muted">
            esc
          </kbd>
        </div>

        <div className="max-h-[52vh] overflow-y-auto py-2">
          {commands.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-ink-muted">
              Nothing matches “{query}”.
            </p>
          ) : (
            grouped.map(([group, items]) => (
              <div key={group} className="mb-1">
                <p className="px-4 py-1 text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                  {group}
                </p>
                {items.map((command) => {
                  const index = commands.indexOf(command);
                  return (
                    <button
                      key={command.id}
                      type="button"
                      onMouseEnter={() => setActive(index)}
                      onClick={() => go(command)}
                      className={`flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm transition ${
                        index === active ? "bg-white/8" : ""
                      }`}
                    >
                      <span className="text-ink-muted">{command.icon}</span>
                      <span className="flex-1 truncate">{command.label}</span>
                      <span className="truncate text-xs text-ink-muted">
                        {command.hint}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
