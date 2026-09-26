/**
 * The marketing footer (landing and login). Every link resolves: in-page
 * anchors on the landing page, console routes that exist, and the project's
 * repository. There are no Terms or Privacy links because there are no such
 * pages; the day they exist, they go in the Project group.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { BRAND } from "../../brand";
import { APP, LOGIN } from "../../routes";
import { Logo } from "../Logo";
import { IconExternal } from "../icons";
import { SECTIONS } from "./SiteHeader";

type FooterLink =
  | { label: string; anchor: string }
  | { label: string; to: string }
  | { label: string; href: string };

const GROUPS: Array<{ heading: string; links: FooterLink[] }> = [
  {
    heading: "Product",
    links: SECTIONS.map((s) => ({ label: s.label === "Trust" ? "Trust and safety" : s.label, anchor: s.id })),
  },
  {
    heading: "Console",
    links: [
      { label: "Sign in", to: LOGIN },
      { label: "Overview", to: APP },
      { label: "Test lab", to: `${APP}/test-lab` },
      { label: "Templates", to: `${APP}/templates` },
    ],
  },
  {
    heading: "Project",
    links: [
      { label: "Source on GitHub", href: BRAND.repoUrl },
      { label: "Setup guide", href: BRAND.setupUrl },
      { label: "Before dialling real numbers", href: BRAND.complianceUrl },
    ],
  },
];

const linkClass =
  "inline-flex items-center gap-1 rounded-sm text-sm text-ink-secondary transition-colors hover:text-ink hover:underline hover:underline-offset-4";

/** `onLanding`: anchors are plain `#id` jumps; elsewhere they go to `/#id`. */
export function SiteFooter({ onLanding = false }: { onLanding?: boolean }) {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="mx-auto w-full max-w-6xl px-4 pb-10 pt-14 sm:px-6 lg:px-8">
        <div className="grid gap-10 md:grid-cols-[1.4fr_repeat(3,1fr)] md:gap-8">
          <div className="max-w-xs">
            <Link to="/" className="inline-flex rounded-md" aria-label={`${BRAND.name} home`}>
              <Logo size={28} />
            </Link>
            <p className="mt-4 text-sm leading-relaxed text-ink-secondary">{BRAND.tagline}</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              <span lang="hi">{BRAND.nativeName}</span> means “{BRAND.meaning}”. Calls in{" "}
              {BRAND.languages.map((l, i) => (
                <span key={l.code}>
                  <span lang={l.code} dir={l.dir}>
                    {l.native}
                  </span>
                  {i < BRAND.languages.length - 2 ? ", " : i === BRAND.languages.length - 2 ? " and " : "."}
                </span>
              ))}
            </p>
          </div>

          {GROUPS.map((group) => (
            <nav key={group.heading} aria-label={group.heading}>
              <h2 className="text-sm font-semibold text-ink">{group.heading}</h2>
              <ul className="mt-4 space-y-3">
                {group.links.map((link) => (
                  <li key={link.label}>
                    <FooterLinkItem link={link} onLanding={onLanding} />
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="mt-12 border-t border-line pt-6 text-xs text-ink-muted">
          <p>{BRAND.copyright}</p>
        </div>
      </div>
    </footer>
  );
}

function FooterLinkItem({ link, onLanding }: { link: FooterLink; onLanding: boolean }): ReactNode {
  if ("anchor" in link) {
    return (
      <a href={onLanding ? `#${link.anchor}` : `/#${link.anchor}`} className={linkClass}>
        {link.label}
      </a>
    );
  }
  if ("to" in link) {
    return (
      <Link to={link.to} className={linkClass}>
        {link.label}
      </Link>
    );
  }
  return (
    <a href={link.href} target="_blank" rel="noopener noreferrer" className={linkClass}>
      {link.label}
      <IconExternal size={12} className="shrink-0 text-ink-muted" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
