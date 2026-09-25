/**
 * Toasts. A tiny external store so any handler can say `toast.success(...)`
 * without threading a context through; <Toaster /> renders the stack once at
 * the root.
 *
 * Every mutation in the app reports through here: success says what changed,
 * error says what went wrong in the server's own words.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AnimatePresence, m } from "framer-motion";
import { IconAlert, IconCheck, IconClose, IconInfo } from "./icons";
import { T } from "../motion";

type Tone = "success" | "error" | "info";

interface ToastItem {
  id: number;
  tone: Tone;
  title: string;
  description?: string;
}

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((fn) => fn());
}

function push(tone: Tone, title: string, description?: string) {
  const item = { id: nextId++, tone, title, description };
  // Cap the stack: a burst of failures shouldn't bury the page.
  items = [...items, item].slice(-4);
  emit();
  return item.id;
}

export const toast = {
  success: (title: string, description?: string) => push("success", title, description),
  error: (title: string, description?: string) => push("error", title, description),
  info: (title: string, description?: string) => push("info", title, description),
  dismiss: (id: number) => {
    items = items.filter((t) => t.id !== id);
    emit();
  },
};

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
const snapshot = () => items;

const TONE: Record<Tone, { icon: React.ReactNode; className: string; ms: number }> = {
  success: { icon: <IconCheck size={14} />, className: "bg-good/12 text-good", ms: 4500 },
  error: { icon: <IconAlert size={14} />, className: "bg-critical/12 text-critical", ms: 8000 },
  info: { icon: <IconInfo size={14} />, className: "bg-info/12 text-info", ms: 5000 },
};

export function Toaster() {
  const list = useSyncExternalStore(subscribe, snapshot);
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[70] flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6"
    >
      <AnimatePresence initial={false}>
        {list.map((item) => (
          <ToastCard key={item.id} item={item} />
        ))}
      </AnimatePresence>
    </div>
  );
}

function ToastCard({ item }: { item: ToastItem }) {
  const tone = TONE[item.tone];
  const [paused, setPaused] = useState(false);
  const remaining = useRef(tone.ms);
  const startedAt = useRef(Date.now());

  useEffect(() => {
    if (paused) return;
    startedAt.current = Date.now();
    const timer = window.setTimeout(() => toast.dismiss(item.id), remaining.current);
    return () => {
      window.clearTimeout(timer);
      remaining.current -= Date.now() - startedAt.current;
    };
  }, [paused, item.id]);

  return (
    <m.div
      role={item.tone === "error" ? "alert" : "status"}
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 16, transition: T.fast }}
      transition={T.base}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className="pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border border-line bg-raised p-3.5 pr-2.5 elev-3"
    >
      <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${tone.className}`}>
        {tone.icon}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-sm font-medium leading-snug text-ink">{item.title}</p>
        {item.description && (
          <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">{item.description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => toast.dismiss(item.id)}
        aria-label="Dismiss notification"
        className="rounded-md p-1 text-ink-muted transition-colors hover:bg-subtle hover:text-ink"
      >
        <IconClose size={14} />
      </button>
    </m.div>
  );
}
