import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Campaign, type CampaignStatus } from "../api";
import { IconCampaign, IconPlus, IconSearch, IconSparkle } from "../components/icons";
import {
  Badge,
  ButtonLink,
  Card,
  EmptyState,
  ErrorNote,
  Input,
  Page,
  PageHeader,
  Segmented,
  Skeleton,
  StatusBadge,
} from "../components/ui";
import { formatUsd } from "../format";
import { useAsync, useDocumentTitle } from "../hooks";

type Filter = "all" | CampaignStatus;

export default function Campaigns() {
  useDocumentTitle("Campaigns");
  const { data: campaigns, loading, error, reload } = useAsync(() => api.campaigns(), []);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const counts = useMemo(() => {
    const out: Record<Filter, number> = { all: 0, running: 0, paused: 0, draft: 0, completed: 0 };
    (campaigns ?? []).forEach((c) => {
      out.all += 1;
      out[c.status] += 1;
    });
    return out;
  }, [campaigns]);

  const visible = (campaigns ?? []).filter(
    (c) =>
      (filter === "all" || c.status === filter) &&
      (!query.trim() || `${c.name} ${c.goal}`.toLowerCase().includes(query.trim().toLowerCase())),
  );

  return (
    <Page>
      <PageHeader
        icon={<IconCampaign size={18} />}
        title="Campaigns"
        description="Each campaign says what the agent should accomplish, who it calls, and when it may dial. Nothing dials until you press start."
        actions={
          <>
            <ButtonLink to="/templates" variant="secondary" icon={<IconSparkle size={14} />}>
              Templates
            </ButtonLink>
            <ButtonLink to="/campaigns/new" icon={<IconPlus size={14} />}>
              New campaign
            </ButtonLink>
          </>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorNote message={error} onRetry={reload} />
        </div>
      )}

      {!loading && (campaigns?.length ?? 0) > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Segmented
            label="Status"
            size="sm"
            value={filter}
            onChange={setFilter}
            options={(["all", "running", "paused", "draft", "completed"] as const).map((value) => ({
              value,
              label: (
                <>
                  <span className="capitalize">{value}</span>
                  <span className="tnum text-ink-muted">{counts[value]}</span>
                </>
              ),
            }))}
          />
          {(campaigns?.length ?? 0) > 5 && (
            <label className="relative ml-auto w-full sm:w-64">
              <span className="sr-only">Search campaigns</span>
              <IconSearch size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search campaigns" className="pl-9" />
            </label>
          )}
        </div>
      )}

      {loading ? (
        <div className="grid gap-3 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : !campaigns?.length ? (
        <Card>
          <EmptyState
            title="No campaigns yet"
            hint="Start from a template — appointment reminders, lead qualification, candidate screening — or write your own brief. Then load contacts and press start."
            action={
              <>
                <ButtonLink to="/templates" icon={<IconSparkle size={14} />}>
                  Browse templates
                </ButtonLink>
                <ButtonLink to="/campaigns/new" variant="secondary">
                  Start from scratch
                </ButtonLink>
              </>
            }
          />
        </Card>
      ) : visible.length === 0 ? (
        <Card>
          <EmptyState compact avatar="thinking" title="No campaigns match" hint="Try another status or search." />
        </Card>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {visible.map((c) => (
            <li key={c.id}>
              <CampaignCard campaign={c} />
            </li>
          ))}
        </ul>
      )}
    </Page>
  );
}

function CampaignCard({ campaign: c }: { campaign: Campaign }) {
  const progress = c.total_contacts ? (c.completed / c.total_contacts) * 100 : 0;
  return (
    <Link to={`/campaigns/${c.id}`} className="block h-full rounded-xl">
      <Card interactive className="flex h-full flex-col px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <h2 className="min-w-0 truncate text-base font-semibold tracking-tight text-ink">{c.name}</h2>
          <StatusBadge status={c.status} />
        </div>
        <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-ink-secondary">{c.goal}</p>

        <div className="mt-auto pt-4">
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-ink-muted">
              <span className="tnum font-semibold text-ink">{c.completed}</span> of{" "}
              <span className="tnum">{c.total_contacts}</span> contacts done
            </span>
            <span className="tnum text-ink-muted">{Math.round(progress)}%</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-subtle-strong">
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-700 ease-[var(--ease-out)]"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Badge tone="neutral" className="uppercase">{c.language}</Badge>
            {c.pending > 0 && <Badge tone="neutral">{c.pending} pending</Badge>}
            {c.needs_review > 0 && <Badge tone="warning">{c.needs_review} to review</Badge>}
            {c.spend_usd > 0 && (
              <span className="tnum ml-auto text-xs text-ink-muted">
                {formatUsd(c.spend_usd)}
                {c.budget_usd != null && ` / ${formatUsd(c.budget_usd, 0)}`}
              </span>
            )}
          </div>
        </div>
      </Card>
    </Link>
  );
}
