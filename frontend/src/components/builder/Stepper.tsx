import { useEffect, useRef } from "react";
import { IconAlert, IconCheck } from "../icons";
import { cx } from "../ui";
import { useBuilder } from "./context";
import { STEPS, type StepId } from "./draft";

type Mark = "done" | "attention" | "todo";

function useMarks(): Record<StepId, Mark> {
  const { draft, contactCount, blockers } = useBuilder();
  const f = draft.form;
  const flagged = new Set(blockers.filter((b) => b.level === "block").map((b) => b.fix.step));
  const mark = (step: StepId, done: boolean): Mark => (flagged.has(step) ? "attention" : done ? "done" : "todo");
  return {
    basics: mark("basics", !!f.name.trim() && !!f.goal.trim()),
    agent: mark("agent", !!f.greeting.trim()),
    tools: mark("tools", (f.mcp_tools?.length ?? 0) + (f.mcp_post_call_tools?.length ?? 0) > 0),
    contacts: mark("contacts", contactCount > 0),
    schedule: mark("schedule", f.calling_days.length > 0 && f.calling_hours_start < f.calling_hours_end),
    review: "todo",
  };
}

export function Stepper({ current }: { current: StepId }) {
  const { goTo } = useBuilder();
  const marks = useMarks();
  const listRef = useRef<HTMLOListElement>(null);
  const index = STEPS.findIndex((s) => s.id === current);

  // Keep the current step in view on narrow screens, where the list scrolls.
  useEffect(() => {
    // Scroll only the list: scrollIntoView would also nudge the page's own
    // scroller, which hides its horizontal overflow but can still be moved.
    const list = listRef.current;
    const el = list?.querySelector<HTMLElement>('[aria-current="step"]')?.parentElement;
    if (list && el && list.scrollWidth > list.clientWidth) {
      list.scrollTo({ left: el.offsetLeft - (list.clientWidth - el.clientWidth) / 2, behavior: "smooth" });
    }
  }, [current]);

  return (
    <nav aria-label="Campaign steps" className="-mx-4 sm:mx-0">
      <ol ref={listRef} className="relative flex items-center gap-1 overflow-x-auto px-4 pb-1 scrollbar-none sm:px-0">
        {STEPS.map((step, i) => {
          const active = step.id === current;
          const mark = marks[step.id];
          return (
            <li key={step.id} className="flex shrink-0 items-center gap-1">
              {i > 0 && <span aria-hidden className={cx("h-px w-4 shrink-0 sm:w-6", i <= index ? "bg-brand/50" : "bg-line-strong")} />}
              <button
                type="button"
                onClick={() => goTo(step.id)}
                aria-current={active ? "step" : undefined}
                className={cx(
                  "flex h-9 items-center gap-2 rounded-full pl-1 pr-3 text-sm transition-colors duration-150",
                  active ? "bg-brand/10 font-medium text-ink" : "text-ink-secondary hover:bg-subtle hover:text-ink",
                )}
              >
                <span
                  className={cx(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tnum transition-colors duration-200",
                    active
                      ? "border-brand bg-brand text-on-brand"
                      : mark === "done"
                        ? "border-good/40 bg-good/10 text-good"
                        : mark === "attention"
                          ? "border-warning/50 bg-warning/10 text-warning"
                          : "border-line-strong bg-surface text-ink-muted",
                  )}
                >
                  {!active && mark === "done" ? (
                    <IconCheck size={13} />
                  ) : !active && mark === "attention" ? (
                    <IconAlert size={13} />
                  ) : (
                    i + 1
                  )}
                </span>
                <span className="whitespace-nowrap">
                  <span className="lg:hidden">{step.short}</span>
                  <span className="hidden lg:inline">{step.label}</span>
                </span>
                <span className="sr-only">{mark === "done" ? "(complete)" : mark === "attention" ? "(needs attention)" : ""}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
