/**
 * Test lab — three ways to try a campaign before anyone real is called:
 *   Simulated caller  a model plays the person (fast, repeatable)
 *   Call a phone      the agent rings your own phone, and you watch it live
 *   Browser mic       you are the person, through the browser's microphone
 *
 * The campaign choice is shared across the three tabs (and seeded from
 * ?campaign=), so switching mode never loses it.
 */

import { useEffect, useState } from "react";
import { NavLink, Outlet, useOutletContext, useSearchParams } from "react-router-dom";
import { api, type Campaign } from "../api";
import { IconFlask, IconMic, IconPhone, IconSparkle } from "../components/icons";
import { ButtonLink, Field, Page, PageHeader, Select, Skeleton, cx } from "../components/ui";
import { useAsync, useDocumentTitle } from "../hooks";

export interface TestLabContext {
  campaigns: Campaign[] | null;
  campaignsLoading: boolean;
  campaignId: string;
  setCampaignId: (id: string) => void;
  campaign: Campaign | undefined;
}

export const useTestLab = () => useOutletContext<TestLabContext>();

const TABS = [
  { to: "/test-lab", label: "Simulated caller", icon: <IconSparkle size={15} />, end: true },
  { to: "/test-lab/phone", label: "Call a phone", icon: <IconPhone size={15} />, end: false },
  { to: "/test-lab/mic", label: "Browser mic", icon: <IconMic size={15} />, end: false },
];

export default function TestLab() {
  useDocumentTitle("Test lab");
  const campaigns = useAsync(() => api.campaigns(), []);
  const [params, setParams] = useSearchParams();
  const [campaignId, setCampaignIdState] = useState(params.get("campaign") ?? "");

  const setCampaignId = (id: string) => {
    setCampaignIdState(id);
    const next = new URLSearchParams(params);
    if (id) next.set("campaign", id);
    else next.delete("campaign");
    setParams(next, { replace: true });
  };

  // With a single campaign there's nothing to choose.
  useEffect(() => {
    if (!campaignId && campaigns.data?.length === 1) setCampaignIdState(campaigns.data[0].id);
  }, [campaigns.data, campaignId]);

  const context: TestLabContext = {
    campaigns: campaigns.data,
    campaignsLoading: campaigns.loading,
    campaignId,
    setCampaignId,
    campaign: campaigns.data?.find((c) => c.id === campaignId),
  };

  return (
    <Page width="wide">
      <PageHeader
        icon={<IconFlask size={18} />}
        title="Test lab"
        description="Rehearse a campaign before anyone real is called. Same prompt, same models, same extractor — only who answers changes."
      />
      {/* Three equal columns on a phone (icon over label) so no tab is ever
          cut off; a normal tab row from sm up. */}
      <nav aria-label="Test mode" className="mb-6 grid grid-cols-3 border-b border-line sm:flex sm:gap-1">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={{ pathname: tab.to, search: campaignId ? `?campaign=${campaignId}` : "" }}
            end={tab.end}
            className={({ isActive }) =>
              cx(
                "-mb-px inline-flex min-w-0 flex-col items-center justify-center gap-1 border-b-2 px-1 py-2 text-center text-xs font-medium leading-tight transition-colors duration-150",
                "sm:h-10 sm:shrink-0 sm:flex-row sm:gap-2 sm:px-3 sm:py-0 sm:text-sm",
                isActive ? "border-brand text-ink" : "border-transparent text-ink-muted hover:border-line-strong hover:text-ink",
              )
            }
          >
            {tab.icon}
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet context={context} />
    </Page>
  );
}

/** The campaign picker every tab puts at the top of its setup card. */
export function CampaignField({ disabled = false }: { disabled?: boolean }) {
  const { campaigns, campaignsLoading, campaignId, setCampaignId } = useTestLab();
  if (!campaignsLoading && campaigns && campaigns.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-strong px-4 py-4 text-center">
        <p className="text-sm font-medium text-ink">No campaigns yet</p>
        <p className="mt-1 text-xs text-ink-muted">Tests run against a campaign's prompt and models.</p>
        <ButtonLink to="/templates" size="sm" className="mt-3">
          Start from a template
        </ButtonLink>
      </div>
    );
  }
  return (
    <Field label="Campaign" hint="Its goal, greeting, guardrails, language and models are used as-is.">
      {campaignsLoading ? (
        <Skeleton className="h-9 w-full" />
      ) : (
        <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} disabled={disabled}>
          <option value="">Choose a campaign…</option>
          {(campaigns ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      )}
    </Field>
  );
}
