/** A server's tools: a readable title, the real name, and what it does. */

import type { ReactNode } from "react";
import type { McpTool } from "../../api";
import { cx } from "../ui";
import { toolTitle } from "./toolText";

export function ToolSummaryList({
  tools,
  action,
  className = "",
}: {
  tools: McpTool[];
  /** Rendered at the end of each row, e.g. a "Try it" button. */
  action?: (tool: McpTool) => ReactNode;
  className?: string;
}) {
  return (
    <ul className={cx("divide-y divide-line rounded-lg border border-line", className)}>
      {tools.map((tool) => (
        <li key={tool.id} className="flex items-start gap-3 px-3.5 py-2.5">
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-medium text-ink">{toolTitle(tool.name)}</span>
              <code className="font-mono text-2xs text-ink-muted">{tool.name}</code>
            </p>
            {tool.description && (
              <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-ink-secondary" title={tool.description}>
                {tool.description}
              </p>
            )}
          </div>
          {action && <div className="shrink-0">{action(tool)}</div>}
        </li>
      ))}
    </ul>
  );
}
