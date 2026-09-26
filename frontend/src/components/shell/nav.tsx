/**
 * The console's map: nav groups, page titles for breadcrumbs, and the `g`
 * shortcuts. The sidebar, the command palette, the breadcrumbs and the
 * shortcuts dialog all read this, so a new page is added in one place.
 */

import type { ReactNode } from "react";
import {
  IconBlock,
  IconCampaign,
  IconChip,
  IconDashboard,
  IconFlask,
  IconLive,
  IconPhone,
  IconReview,
  IconSettings,
  IconSparkle,
} from "../icons";

export interface NavItem {
  to: string;
  /** Active only on an exact match (the overview is the prefix of every page). */
  end?: boolean;
  label: string;
  hint: string;
  icon: (size: number) => ReactNode;
  /** Letter pressed after `g` to jump here. */
  key: string;
  badge?: "review" | "live";
}

export const NAV_GROUPS: Array<{ heading?: string; items: NavItem[] }> = [
  {
    items: [
      { to: "/app", end: true, label: "Overview", hint: "Today at a glance", key: "o", icon: (s) => <IconDashboard size={s} /> },
    ],
  },
  {
    heading: "Operate",
    items: [
      { to: "/app/campaigns", label: "Campaigns", hint: "Who to call and what to say", key: "p", icon: (s) => <IconCampaign size={s} /> },
      { to: "/app/calls", label: "Calls", hint: "Every conversation, saved", key: "c", icon: (s) => <IconPhone size={s} /> },
      { to: "/app/review", label: "Review queue", hint: "Outcomes that need a human", key: "r", icon: (s) => <IconReview size={s} />, badge: "review" },
      { to: "/app/live", label: "Live", hint: "Calls on the line right now", key: "l", icon: (s) => <IconLive size={s} />, badge: "live" },
    ],
  },
  {
    heading: "Build",
    items: [
      { to: "/app/test-lab", label: "Test lab", hint: "Rehearse before you dial", key: "t", icon: (s) => <IconFlask size={s} /> },
      { to: "/app/templates", label: "Templates", hint: "Ready-made campaigns", key: "e", icon: (s) => <IconSparkle size={s} /> },
    ],
  },
  {
    heading: "Configure",
    items: [
      { to: "/app/models", label: "Models", hint: "Pick the LLMs and see the cost", key: "m", icon: (s) => <IconChip size={s} /> },
      { to: "/app/settings", label: "Integrations", hint: "Services and their status", key: "i", icon: (s) => <IconSettings size={s} /> },
      { to: "/app/suppressions", label: "Do not call", hint: "Numbers never dialled", key: "d", icon: (s) => <IconBlock size={s} /> },
    ],
  },
];

export const NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

export interface Crumb {
  label: string;
  to?: string;
}

/** Breadcrumb trail for a console path. `dynamic` is a page-supplied last crumb (a campaign name). */
export function crumbsFor(pathname: string, dynamic: string | null): Crumb[] {
  // Everything below lives under /app; match on the part after it.
  const path = pathname.replace(/^\/app(?=\/|$)/, "") || "/";
  const test = (re: RegExp) => re.test(path);
  if (path === "/") return [{ label: "Overview" }];
  if (test(/^\/campaigns\/new/)) return [{ label: "Campaigns", to: "/app/campaigns" }, { label: "New campaign" }];
  if (test(/^\/campaigns\/[^/]+/)) return [{ label: "Campaigns", to: "/app/campaigns" }, { label: dynamic ?? "Campaign" }];
  if (test(/^\/review/)) return [{ label: "Calls", to: "/app/calls" }, { label: "Review queue" }];
  if (test(/^\/test-lab\/phone/)) return [{ label: "Test lab", to: "/app/test-lab" }, { label: "Call a phone" }];
  if (test(/^\/test-lab\/mic/)) return [{ label: "Test lab", to: "/app/test-lab" }, { label: "Browser mic" }];
  if (test(/^\/test-lab/)) return [{ label: "Test lab", to: "/app/test-lab" }, { label: "Simulated caller" }];
  const item = NAV_ITEMS.find((i) => !i.end && (pathname === i.to || pathname.startsWith(`${i.to}/`)));
  return item ? [{ label: item.label }] : [{ label: "Not found" }];
}

/** A plain-language name for a console URL ("Calls"), for "you'll return to…" copy. */
export function pageNameFor(pathname: string): string | null {
  const crumbs = crumbsFor(pathname, null);
  const last = crumbs[crumbs.length - 1]?.label;
  return last && last !== "Not found" ? last : null;
}
