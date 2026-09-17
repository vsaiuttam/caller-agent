import { Link } from "react-router-dom";
import { api } from "../api";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  PageWrapper,
  Skeleton,
  StatusBadge,
} from "../components/ui";
import { useAsync } from "../hooks";

export default function Campaigns() {
  const { data: campaigns, loading, error } = useAsync(() => api.campaigns());

  return (
    <PageWrapper className="mx-auto max-w-5xl px-3 py-4 sm:px-6 sm:py-5">
      <header className="mb-5 flex items-start justify-between gap-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Campaigns</h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            Each campaign defines what the agent says, who it calls, and when it may
            dial.
          </p>
        </div>
        <Link to="/campaigns/new">
          <Button>New campaign</Button>
        </Link>
      </header>

      {error && <ErrorNote message={error} />}

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : !campaigns?.length ? (
        <Card hover={false}>
          <EmptyState
            title="No campaigns yet"
            hint="Create one, load your contact list, then start it. Nothing dials until you press start."
            action={
              <Link to="/campaigns/new">
                <Button>Create your first campaign</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <ul className="space-y-2">
          {campaigns.map((c) => {
            const progress = c.total_contacts
              ? (c.completed / c.total_contacts) * 100
              : 0;

            return (
              <li key={c.id}>
                <Link to={`/campaigns/${c.id}`} className="block">
                  <Card className="px-5 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2.5">
                          <span className="font-semibold">{c.name}</span>
                          <StatusBadge status={c.status} />
                          {c.needs_review > 0 && (
                            <span className="rounded-md border border-warning/20 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
                              {c.needs_review} to review
                            </span>
                          )}
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-sm text-ink-secondary">
                          {c.goal}
                        </p>
                      </div>
                      <div className="tnum shrink-0 text-right text-xs text-ink-muted">
                        <div className="text-sm font-bold text-ink">
                          {c.completed}
                          <span className="text-ink-muted">/{c.total_contacts}</span>
                        </div>
                        <div className="mt-0.5">{c.pending} pending</div>
                      </div>
                    </div>

                    {c.total_contacts > 0 && (
                      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-elevated">
                        <div
                          className="h-full rounded-full bg-brand transition-[width] duration-700 ease-out"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    )}
                  </Card>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </PageWrapper>
  );
}
