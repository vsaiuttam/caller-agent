/**
 * The console's slim footer, at the end of every page: which build this is,
 * the same system status as the top bar, the keyboard shortcuts, and where
 * the documentation and source live. One line on desktop; it wraps on phones.
 */

import { Link } from "react-router-dom";
import { BRAND } from "../../brand";
import { useHealth } from "../../data";
import { IconExternal, IconKeyboard } from "../icons";
import { cx } from "../ui";
import { STATUS_DOT, systemStatus } from "./status";

const BUILD = [
  `v${__APP_VERSION__}`,
  __BUILD_SHA__ ? `build ${__BUILD_SHA__}` : null,
  __BUILD_DATE__ ? __BUILD_DATE__ : null,
]
  .filter(Boolean)
  .join(", ");

const link =
  "inline-flex min-h-6 items-center gap-1 rounded-sm text-ink-secondary transition-colors hover:text-ink hover:underline underline-offset-4";

export function AppFooter({ onShortcuts }: { onShortcuts: () => void }) {
  const { health, error } = useHealth();
  const status = systemStatus(health, error);
  return (
    <footer className="border-t border-line px-4 py-4 text-xs text-ink-muted sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-5 gap-y-2">
        <span className="font-medium text-ink-secondary">{BRAND.name}</span>
        <span className="tnum" title="Console version and build">
          {BUILD}
        </span>
        <Link to="/app/settings?tab=services" className={link} title={status.detail}>
          <span className={cx("h-1.5 w-1.5 rounded-full", STATUS_DOT[status.tone])} aria-hidden />
          <span>
            <span className="sr-only">System status: </span>
            {status.label}
          </span>
        </Link>
        <span className="flex flex-1 flex-wrap items-center justify-start gap-x-5 gap-y-2 sm:justify-end">
          <button type="button" onClick={onShortcuts} className={link}>
            <IconKeyboard size={13} aria-hidden /> Keyboard shortcuts
          </button>
          <a href={BRAND.docsUrl} target="_blank" rel="noopener noreferrer" className={link}>
            Docs <IconExternal size={11} />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
          <a href={BRAND.repoUrl} target="_blank" rel="noopener noreferrer" className={link}>
            GitHub <IconExternal size={11} />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </span>
      </div>
    </footer>
  );
}
