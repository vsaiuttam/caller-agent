/**
 * "Tools used" on a saved call: every tool the agent ran, during the call and
 * after it — which app, what it asked for, what came back, how long it took.
 */

import type { ToolCallLog } from "../../api";
import { formatJson, formatMs, formatOffset, prettyText } from "../../format";
import { IconCheck, IconChevronRight, IconClose, IconWrench } from "../icons";
import { Badge, Callout, Card, CardHeader, CodeBlock, Eyebrow, cx } from "../ui";
import { toolTitle } from "./toolText";

export function ToolCallsCard({
  calls,
  startedAt,
  skipped,
}: {
  calls: ToolCallLog[];
  /** The call's start, for "at 01:12" offsets. */
  startedAt: string;
  /** Why after-call tools didn't run, when they didn't. */
  skipped?: string;
}) {
  if (!calls.length && !skipped) return null;
  const during = calls.filter((c) => c.phase === "in_call");
  const after = calls.filter((c) => c.phase === "post_call");
  const failed = calls.filter((c) => !c.ok).length;

  return (
    <Card>
      <CardHeader
        title="Tools used"
        subtitle={`${during.length} during the call · ${after.length} after`}
        icon={<IconWrench size={15} />}
        action={failed > 0 && <Badge tone="critical">{failed} failed</Badge>}
      />
      <div className="space-y-5 px-5 py-4">
        {during.length > 0 && <Group title="During the call" calls={during} startedAt={startedAt} />}
        {after.length > 0 && <Group title="After the call" calls={after} startedAt={startedAt} />}
        {skipped && (
          <Callout tone="info" title="After-call tools didn't run">
            The call was {skipped}. Approving it writes the outcome, but doesn't run them — record anything else by hand.
          </Callout>
        )}
      </div>
    </Card>
  );
}

function Group({ title, calls, startedAt }: { title: string; calls: ToolCallLog[]; startedAt: string }) {
  return (
    <section>
      <Eyebrow className="mb-2">{title}</Eyebrow>
      <ol className="space-y-2">
        {calls.map((call, i) => (
          <li key={`${call.at}-${i}`}>
            <Entry call={call} startedAt={startedAt} />
          </li>
        ))}
      </ol>
    </section>
  );
}

function Entry({ call, startedAt }: { call: ToolCallLog; startedAt: string }) {
  return (
    <div className={cx("rounded-lg border", call.ok ? "border-line" : "border-critical/30")}>
      <div className="flex items-start justify-between gap-3 px-3.5 py-2.5">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className={cx(
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
              call.ok ? "bg-good/12 text-good" : "bg-critical/12 text-critical",
            )}
          >
            {call.ok ? <IconCheck size={11} /> : <IconClose size={11} />}
            <span className="sr-only">{call.ok ? "Succeeded" : "Failed"}</span>
          </span>
          <div className="min-w-0">
            <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-medium text-ink">{toolTitle(call.tool)}</span>
              <code className="break-all font-mono text-2xs text-ink-muted">{call.tool}</code>
            </p>
            <p className="mt-0.5 text-xs text-ink-muted">
              {call.server}
              {call.phase === "in_call" && <span className="tnum"> · at {formatOffset(call.at, startedAt)}</span>}
            </p>
          </div>
        </div>
        {call.duration_ms != null && <span className="tnum shrink-0 text-xs text-ink-secondary">{formatMs(call.duration_ms)}</span>}
      </div>
      <div className="space-y-2 border-t border-line px-3.5 py-2.5">
        {call.ok ? (
          call.excerpt ? (
            <CodeBlock>{prettyText(call.excerpt)}</CodeBlock>
          ) : (
            <p className="text-xs text-ink-muted">It returned no text.</p>
          )
        ) : (
          <p className="break-words text-xs text-critical">{call.error ?? "It failed without saying why."}</p>
        )}
        <details className="group">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-xs font-medium text-ink-secondary transition-colors hover:text-ink [&::-webkit-details-marker]:hidden">
            <IconChevronRight size={12} className="transition-transform group-open:rotate-90" />
            Arguments
          </summary>
          <CodeBlock className="mt-1.5">{formatJson(call.arguments)}</CodeBlock>
        </details>
      </div>
    </div>
  );
}
