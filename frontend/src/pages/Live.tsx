/**
 * Live — every call on the line right now (§6). Pick one to open its
 * console: listen in on the transcript, whisper to the agent, or end it.
 *
 * The list is GET /api/calls/live, refreshed on a timer and on every call
 * event (see data.tsx). A call you're watching stays open after it drops off
 * the list, so you see how it ended.
 */

import { useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { CallConsole } from "../components/live/CallConsole";
import { LiveCallCard } from "../components/live/LiveCallCard";
import { IconFlask, IconLive, IconPhone } from "../components/icons";
import { Badge, ButtonLink, Callout, Card, EmptyState, Page, PageHeader, Skeleton } from "../components/ui";
import { useLiveCalls } from "../data";
import { useAsync, useDocumentTitle, useMediaQuery, useNow } from "../hooks";

export default function Live() {
  useDocumentTitle("Live");
  const { calls, supported, loaded } = useLiveCalls();
  const campaigns = useAsync(() => api.campaigns(), []);
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("call");
  const now = useNow(1000, calls.length > 0);
  const wide = useMediaQuery("(min-width: 1024px)");
  const consoleRef = useRef<HTMLDivElement>(null);

  const campaignName = useMemo(() => {
    const names = new Map((campaigns.data ?? []).map((c) => [c.id, c.name]));
    return (id: string | null) => (id ? names.get(id) : undefined);
  }, [campaigns.data]);

  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("call", id);
    else next.delete("call");
    setParams(next, { replace: true });
  };

  // Open the only call automatically — there's nothing else to choose.
  useEffect(() => {
    if (!selectedId && calls.length === 1) select(calls[0].call_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calls.length, selectedId]);

  // On a phone the console sits under the list; bring it into view.
  useEffect(() => {
    if (selectedId && !wide) consoleRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [selectedId, wide]);

  const selected = calls.find((c) => c.call_id === selectedId);

  return (
    <Page width="wide">
      <PageHeader
        icon={<IconLive size={18} />}
        title="Live"
        meta={
          calls.length > 0 ? (
            <Badge tone="good" dot pulse>
              {calls.length} on the line
            </Badge>
          ) : undefined
        }
        description="Calls happening right now. Open one to follow the transcript, whisper guidance to the agent, or end it."
      />

      {!supported && (
        <Callout tone="info" title="This server doesn't report live calls yet" className="mb-5">
          Live calls need the v2 backend (<code className="font-mono text-2xs">GET /api/calls/live</code>). Test calls placed from
          the Test lab still stream in their own console.
        </Callout>
      )}

      {!loaded ? (
        <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-96 rounded-xl" />
        </div>
      ) : calls.length === 0 && !selectedId ? (
        <Card>
          <EmptyState
            title="Nobody's on the line right now"
            hint="Calls appear here the moment they're dialled — from running campaigns or from the Test lab. This page updates by itself."
            action={
              <>
                <ButtonLink to="/test-lab/phone" icon={<IconPhone size={14} />}>
                  Place a test call
                </ButtonLink>
                <ButtonLink to="/campaigns" variant="secondary" icon={<IconFlask size={14} />}>
                  Go to campaigns
                </ButtonLink>
              </>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)] lg:items-start">
          <section aria-label="Calls on the line" className="space-y-2 lg:sticky lg:top-20">
            {calls.length === 0 ? (
              <p className="rounded-xl border border-dashed border-line-strong px-4 py-6 text-center text-xs text-ink-muted">
                No other calls are live.
              </p>
            ) : (
              calls.map((call) => (
                <LiveCallCard
                  key={call.call_id}
                  call={call}
                  now={now}
                  campaignName={campaignName(call.campaign_id)}
                  selected={call.call_id === selectedId}
                  onSelect={() => select(call.call_id)}
                  animated={calls.length <= 6}
                />
              ))
            )}
          </section>

          <div ref={consoleRef} className="min-w-0 scroll-mt-20">
            {selectedId ? (
              <CallConsole
                key={selectedId}
                callId={selectedId}
                seed={selected}
                mode={selected?.is_test ? "test" : "watch"}
                onClose={() => select(null)}
              />
            ) : (
              <Card>
                <EmptyState
                  avatar="listening"
                  title="Pick a call to listen in"
                  hint="You'll see the transcript as it streams, and you can whisper to the agent or end the call."
                />
              </Card>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}
