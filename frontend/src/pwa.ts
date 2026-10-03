/**
 * The installable app: registers the service worker (production builds only,
 * so dev never serves a stale bundle) and keeps Chrome's install prompt so
 * the console can offer "Install app" from its own button.
 */

import { useSyncExternalStore } from "react";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: InstallPromptEvent | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

export function isStandalone(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

export function registerPwa(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferred = event as InstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    notify();
  });
  if (import.meta.env.PROD && "serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // No offline shell; the console works exactly as before.
      });
    });
  }
}

/** Whether the browser will install the app now, and the action that does it. */
export function useInstallPrompt(): { canInstall: boolean; install: () => Promise<boolean> } {
  const canInstall = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => deferred !== null,
    () => false,
  );
  const install = async () => {
    const event = deferred;
    if (!event) return false;
    deferred = null;
    notify();
    await event.prompt();
    return (await event.userChoice).outcome === "accepted";
  };
  return { canInstall, install };
}
