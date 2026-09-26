import { Link, useLocation } from "react-router-dom";
import { BRAND } from "../brand";
import { AgentAvatar } from "../components/AgentAvatar";
import { Logo } from "../components/Logo";
import { IconArrowLeft, IconDashboard } from "../components/icons";
import { MOD_KEY } from "../components/ShortcutsDialog";
import { Button, ButtonLink, Page } from "../components/ui";
import { useDocumentTitle } from "../hooks";
import { APP } from "../routes";

/**
 * 404. Inside the console (`scope="app"`) it offers the overview and the
 * command palette; on the public site it offers the home page and the console.
 */
export default function NotFound({ scope = "app" }: { scope?: "app" | "site" }) {
  const location = useLocation();
  useDocumentTitle("Not found");
  const site = scope === "site";

  const body = (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <AgentAvatar state="thinking" size="lg" />
      <p className="tnum mt-6 text-sm font-medium text-brand">404</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">We couldn't find that page</h1>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-ink-secondary">
        Nothing lives at{" "}
        <code className="font-mono rounded bg-subtle px-1.5 py-0.5 text-xs break-all">{location.pathname}</code>.{" "}
        {site
          ? "The console now lives under /app."
          : `It may have moved. The command palette (${MOD_KEY} K) can find it.`}
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Button variant="secondary" icon={<IconArrowLeft size={14} />} onClick={() => window.history.back()}>
          Go back
        </Button>
        {site ? (
          <ButtonLink to="/">Go to the home page</ButtonLink>
        ) : (
          <ButtonLink to={APP} icon={<IconDashboard size={15} />}>
            Overview
          </ButtonLink>
        )}
      </div>
    </div>
  );

  if (!site) return <Page width="narrow">{body}</Page>;

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <header className="mx-auto flex h-16 w-full max-w-6xl items-center px-4 sm:px-6 lg:px-8">
        <Link to="/" className="rounded-md" aria-label={`${BRAND.name} home`}>
          <Logo size={26} />
        </Link>
      </header>
      <main id="main" className="flex-1">
        <Page width="narrow">{body}</Page>
      </main>
    </div>
  );
}
