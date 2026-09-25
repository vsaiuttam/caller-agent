import { useLocation } from "react-router-dom";
import { AgentAvatar } from "../components/AgentAvatar";
import { IconArrowLeft, IconDashboard } from "../components/icons";
import { MOD_KEY } from "../components/ShortcutsDialog";
import { Button, ButtonLink, Page } from "../components/ui";
import { useDocumentTitle } from "../hooks";

export default function NotFound() {
  const location = useLocation();
  useDocumentTitle("Not found");
  return (
    <Page width="narrow">
      <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
        <AgentAvatar state="thinking" size="lg" />
        <p className="tnum mt-6 text-sm font-medium text-brand">404</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">We couldn't find that page</h1>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-ink-secondary">
          Nothing lives at <code className="font-mono rounded bg-subtle px-1.5 py-0.5 text-xs">{location.pathname}</code>.
          It may have moved in the redesign — the command palette ({MOD_KEY} K) can find it.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button variant="secondary" icon={<IconArrowLeft size={14} />} onClick={() => window.history.back()}>
            Go back
          </Button>
          <ButtonLink to="/dashboard" icon={<IconDashboard size={15} />}>
            Overview
          </ButtonLink>
        </div>
      </div>
    </Page>
  );
}
