/**
 * Things that float above the page: dialogs, drawers, popovers, tooltips.
 *
 * Dialogs and drawers are portalled, trap focus while open, close on Escape
 * or a backdrop click, lock page scroll, and hand focus back to whatever
 * opened them. Popovers and tooltips stay in the flow, anchored to their
 * trigger.
 */

import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, m } from "framer-motion";
import { IconClose } from "./icons";
import { DUR, EASE_OUT, T } from "../motion";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

let scrollLocks = 0;

/** Trap Tab inside `ref` while active; Escape calls `onEscape`; restore focus after. */
function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean, onEscape: () => void) {
  const escapeRef = useRef(onEscape);
  escapeRef.current = onEscape;

  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement as HTMLElement | null;

    scrollLocks += 1;
    document.body.style.overflow = "hidden";

    // Focus after the enter animation has mounted the panel.
    const raf = requestAnimationFrame(() => {
      const panel = ref.current;
      if (!panel) return;
      const preferred = panel.querySelector<HTMLElement>("[data-autofocus]");
      const first = preferred ?? panel.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? panel).focus();
    });

    const onKey = (event: KeyboardEvent) => {
      const panel = ref.current;
      if (!panel) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        escapeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (!nodes.length) {
        event.preventDefault();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey, true);
      scrollLocks -= 1;
      if (scrollLocks <= 0) {
        scrollLocks = 0;
        document.body.style.overflow = "";
      }
      previous?.focus?.();
    };
  }, [active, ref]);
}

// ---------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------

const DIALOG_WIDTH = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" } as const;

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: keyof typeof DIALOG_WIDTH;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useFocusTrap(panel, open, onClose);

  return createPortal(
    <AnimatePresence>
      {open && (
        <m.div
          key="dialog"
          className="fixed inset-0 z-[60] flex items-end justify-center p-0 sm:items-center sm:p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={T.fast}
        >
          <div className="absolute inset-0 bg-[var(--overlay)] backdrop-blur-[2px]" onClick={onClose} />
          <m.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descId : undefined}
            tabIndex={-1}
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={T.base}
            className={`relative w-full ${DIALOG_WIDTH[size]} max-h-[90dvh] overflow-y-auto rounded-t-2xl border border-line bg-raised elev-3 outline-none sm:rounded-2xl`}
          >
            <div className="flex items-start justify-between gap-4 px-5 pt-5">
              <div className="min-w-0">
                <h2 id={titleId} className="text-base font-semibold tracking-tight text-ink">
                  {title}
                </h2>
                {description && (
                  <p id={descId} className="mt-1 text-sm leading-relaxed text-ink-secondary">
                    {description}
                  </p>
                )}
              </div>
              <CloseButton onClick={onClose} />
            </div>
            {children && <div className="px-5 pt-4">{children}</div>}
            <div className="safe-bottom flex flex-wrap justify-end gap-2 px-5 pb-5 pt-5">{footer}</div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------

export function Drawer({
  open,
  onClose,
  side = "right",
  title,
  description,
  children,
  footer,
  width = "max-w-lg",
  hideHeader = false,
  label,
}: {
  open: boolean;
  onClose: () => void;
  side?: "left" | "right";
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Tailwind max-width class. */
  width?: string;
  /** For drawers that bring their own header (the mobile nav). */
  hideHeader?: boolean;
  /** Accessible name when there's no visible title. */
  label?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(panel, open, onClose);
  const offscreen = side === "right" ? "100%" : "-100%";

  return createPortal(
    <AnimatePresence>
      {open && (
        <m.div
          key="drawer"
          className={`fixed inset-0 z-[60] flex ${side === "right" ? "justify-end" : "justify-start"}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: DUR.base } }}
          transition={T.fast}
        >
          <div className="absolute inset-0 bg-[var(--overlay)]" onClick={onClose} />
          <m.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-labelledby={title && !hideHeader ? titleId : undefined}
            aria-label={title && !hideHeader ? undefined : label}
            tabIndex={-1}
            initial={{ x: offscreen }}
            animate={{ x: 0 }}
            exit={{ x: offscreen }}
            transition={{ duration: DUR.slow, ease: EASE_OUT }}
            className={`relative flex h-full w-full ${width} flex-col bg-raised elev-3 outline-none ${
              side === "right" ? "border-l" : "border-r"
            } border-line`}
          >
            {!hideHeader && (
              <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
                <div className="min-w-0">
                  <h2 id={titleId} className="truncate text-base font-semibold tracking-tight">
                    {title}
                  </h2>
                  {description && <p className="mt-0.5 text-xs text-ink-muted">{description}</p>}
                </div>
                <CloseButton onClick={onClose} />
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
            {footer && <div className="safe-bottom border-t border-line px-5 py-3">{footer}</div>}
          </m.div>
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Close"
      className="-mr-1.5 -mt-1 shrink-0 rounded-md p-1.5 text-ink-muted transition-colors hover:bg-subtle hover:text-ink"
    >
      <IconClose size={16} />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Popover — anchored panel for menus (user menu, health details)
// ---------------------------------------------------------------------------

export function Popover({
  open,
  onClose,
  children,
  align = "end",
  className = "",
  label,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  align?: "start" | "end";
  className?: string;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      // The trigger lives in the same relative wrapper; clicks on it toggle.
      const wrapper = ref.current?.parentElement;
      if (wrapper && !wrapper.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        (ref.current?.parentElement?.querySelector("button") as HTMLElement | null)?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <m.div
          ref={ref}
          role="dialog"
          aria-label={label}
          initial={{ opacity: 0, y: -4, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -4, scale: 0.98 }}
          transition={T.fast}
          className={`absolute top-full z-50 mt-2 rounded-xl border border-line bg-raised elev-3 ${
            align === "end" ? "right-0 origin-top-right" : "left-0 origin-top-left"
          } ${className}`}
        >
          {children}
        </m.div>
      )}
    </AnimatePresence>
  );
}

// ---------------------------------------------------------------------------
// Tooltip — hover (after a beat) or keyboard focus (at once)
// ---------------------------------------------------------------------------

const TOOLTIP_SIDE = {
  top: "bottom-full left-1/2 mb-2 -translate-x-1/2",
  bottom: "top-full left-1/2 mt-2 -translate-x-1/2",
  right: "left-full top-1/2 ml-2 -translate-y-1/2",
} as const;

export function Tooltip({
  content,
  children,
  side = "top",
  disabled = false,
}: {
  content: ReactNode;
  children: ReactElement<{ "aria-describedby"?: string }>;
  side?: keyof typeof TOOLTIP_SIDE;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const id = useId();

  useEffect(() => () => window.clearTimeout(timer.current), []);

  if (disabled || !content) return children;

  const show = (delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setOpen(false);
  };

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => show(350)}
      onMouseLeave={hide}
      onFocus={() => show(0)}
      onBlur={hide}
      onKeyDown={(e) => e.key === "Escape" && hide()}
    >
      {isValidElement(children) ? cloneElement(children, { "aria-describedby": open ? id : undefined }) : children}
      <AnimatePresence>
        {open && (
          <m.span
            id={id}
            role="tooltip"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={T.fast}
            className={`pointer-events-none absolute z-[80] w-max max-w-64 rounded-md bg-ink px-2 py-1 text-2xs font-medium leading-snug text-plane elev-2 ${TOOLTIP_SIDE[side]}`}
          >
            {content}
          </m.span>
        )}
      </AnimatePresence>
    </span>
  );
}
