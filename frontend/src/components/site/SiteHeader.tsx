/**
 * The public pages' header: the mark, section anchors (landing only, from
 * 1024px), the theme switch and the one sign-in call to action. 64px tall,
 * sticky, with a blur that exists only to say "this bar floats over the
 * page" (and turns solid under prefers-reduced-transparency).
 */

import { Link } from "react-router-dom";
import { BRAND } from "../../brand";
import { useTheme } from "../../theme";
import { LOGIN } from "../../routes";
import { Logo } from "../Logo";
import { IconMoon, IconSun } from "../icons";
import { ButtonLink, IconButton } from "../ui";

export const SECTIONS = [
  { id: "features", label: "Features" },
  { id: "how-it-works", label: "How it works" },
  { id: "languages", label: "Languages" },
  { id: "trust", label: "Trust" },
] as const;

export function SiteHeader({ anchors = false, cta = true }: { anchors?: boolean; cta?: boolean }) {
  const { theme, toggle } = useTheme();
  return (
    <header className="sticky top-0 z-30 border-b border-line/80 bg-plane/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-2 px-4 sm:px-6 lg:px-8">
        <Link to="/" className="flex shrink-0 items-center gap-2 rounded-md" aria-label={`${BRAND.name} home`}>
          <Logo size={28} />
          <span className="mt-0.5 hidden text-xs text-ink-muted sm:inline" lang="hi" aria-hidden>
            {BRAND.nativeName}
          </span>
        </Link>

        {anchors && (
          <nav aria-label="On this page" className="ml-8 hidden lg:block">
            <ul className="flex items-center gap-1">
              {SECTIONS.map((s) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    className="rounded-md px-3 py-2 text-sm font-medium text-ink-secondary transition-colors hover:bg-subtle hover:text-ink"
                  >
                    {s.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        )}

        <div className="ml-auto flex items-center gap-2">
          <IconButton
            label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            icon={theme === "dark" ? <IconSun size={17} /> : <IconMoon size={17} />}
            onClick={toggle}
          />
          {cta && (
            <ButtonLink to={LOGIN}>
              <span className="sm:hidden">Sign in</span>
              <span className="hidden sm:inline">Sign in to the console</span>
            </ButtonLink>
          )}
        </div>
      </div>
    </header>
  );
}

/** First thing a keyboard user can press on a public page. */
export function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only z-[90] rounded-md bg-raised px-3 py-2 text-sm font-medium text-ink elev-2 focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
    >
      Skip to content
    </a>
  );
}
