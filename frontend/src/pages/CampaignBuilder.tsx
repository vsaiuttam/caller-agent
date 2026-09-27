/**
 * The campaign builder, shared by new (/app/campaigns/new) and edit
 * (/app/campaigns/:id/edit). Six steps with a sticky summary rail; the step
 * lives in ?step= so any step is linkable ("Settings" on a campaign opens the
 * builder at the right one).
 *
 * It never loses work: the draft is autosaved to this browser on every
 * change and offered back on return, apps and model providers connect in
 * place (no trip to Settings), and "Save draft" works on every step.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type Campaign, type CampaignCreate, type CampaignTemplate, type EstimateRequest } from "../api";
import { AgentStep } from "../components/builder/AgentStep";
import { autosaveKey, clearAutosave, readAutosave, writeAutosave } from "../components/builder/autosave";
import { BasicsStep } from "../components/builder/BasicsStep";
import { ContactsStep } from "../components/builder/ContactsStep";
import { BuilderContext, type Blocker, type Builder } from "../components/builder/context";
import {
  STEPS,
  blankDraft,
  draftFromCampaign,
  draftFromTemplate,
  hour,
  isStep,
  payloadOf,
  sameDraft,
  unknownPlaceholders,
  type Draft,
  type StepId,
} from "../components/builder/draft";
import { ReviewStep } from "../components/builder/ReviewStep";
import { ScheduleStep } from "../components/builder/ScheduleStep";
import { Stepper } from "../components/builder/Stepper";
import { SummaryRail } from "../components/builder/SummaryRail";
import { ToolsStep } from "../components/builder/ToolsStep";
import { IconArrowLeft, IconArrowRight, IconCampaign, IconPlay } from "../components/icons";
import { useEstimate } from "../components/models/estimate";
import { money } from "../components/models/meta";
import { ProviderDrawer } from "../components/models/ProviderDrawer";
import { useProviders } from "../components/models/useProviders";
import { useCrumb } from "../components/shell/AppShell";
import { Button, Callout, ErrorNote, Page, PageHeader, Skeleton, StatusBadge, cx, toast } from "../components/ui";
import { useHealth } from "../data";
import { useAsync, useDocumentTitle } from "../hooks";
import { m, AnimatePresence } from "framer-motion";
import { T } from "../motion";

export default function CampaignBuilder() {
  const { id } = useParams();
  const mode: "new" | "edit" = id ? "edit" : "new";
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const handoff = location.state as { template?: CampaignTemplate; language?: string } | null;
  const step: StepId = isStep(params.get("step")) ? (params.get("step") as StepId) : "basics";

  const campaignQ = useAsync(() => (id ? api.campaign(id) : Promise.resolve(null)), [id]);
  const campaign = campaignQ.data;
  useCrumb(mode === "edit" ? (campaign?.name ?? null) : null);
  useDocumentTitle(mode === "edit" ? `Edit ${campaign?.name ?? "campaign"}` : "New campaign");

  const { health } = useHealth();
  const languages = useAsync(() => api.languages(), []);
  const prov = useProviders();
  const [addProvider, setAddProvider] = useState(false);

  const key = autosaveKey(id ?? null);
  const [base, setBase] = useState<Draft | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [restoredAt, setRestoredAt] = useState<number | null>(null);
  const [busy, setBusy] = useState<"save" | "launch" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initialisedFor = useRef<unknown>(undefined);
  const baseRef = useRef<Draft | null>(null);
  baseRef.current = base;

  const goTo = useCallback(
    (next: StepId) => {
      const p = new URLSearchParams(params);
      p.set("step", next);
      setParams(p, { replace: true });
      document.getElementById("main")?.scrollTo({ top: 0, behavior: "smooth" });
    },
    [params, setParams],
  );

  const discard = useCallback(() => {
    clearAutosave(key);
    setDraft(baseRef.current);
    setRestoredAt(null);
  }, [key]);

  // Build the starting draft once the campaign (edit) is known, then offer
  // back anything autosaved that differs from it.
  useEffect(() => {
    if (mode === "edit" && !campaign) return;
    const source = mode === "edit" ? campaign : (handoff?.template ?? "blank");
    if (initialisedFor.current === source) return;
    initialisedFor.current = source;

    const initial =
      mode === "edit" && campaign
        ? draftFromCampaign(campaign)
        : handoff?.template
          ? draftFromTemplate(handoff.template, handoff.language ?? "en")
          : blankDraft();
    setBase(initial);
    const saved = readAutosave(key);
    if (saved && !handoff?.template && !sameDraft(saved.draft, initial)) {
      setDraft(saved.draft);
      setRestoredAt(saved.savedAt);
      if (!isStep(params.get("step"))) goTo(saved.step);
      toast.info(
        "Restored your unsaved changes",
        `From ${new Date(saved.savedAt).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}${saved.contactsDropped ? `. The ${saved.contactsDropped} contacts were too many to keep; drop the file again.` : "."}`,
        { label: "Discard", onClick: discard },
      );
    } else {
      setDraft(initial);
      setRestoredAt(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaign, mode, key]);

  // Autosave, debounced. A draft that matches what's saved leaves nothing behind.
  useEffect(() => {
    if (!draft || !base) return;
    const timer = window.setTimeout(() => {
      if (sameDraft(draft, base)) clearAutosave(key);
      else writeAutosave(key, draft, step);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draft, base, key, step]);

  const update = useCallback((patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d)), []);
  const setForm = useCallback((patch: Partial<CampaignCreate>) => setDraft((d) => (d ? { ...d, form: { ...d.form, ...patch } } : d)), []);

  const contactCount = (campaign?.total_contacts ?? 0) + (draft?.contacts.length ?? 0);
  const f = draft?.form;

  const estimateRequest = useMemo<EstimateRequest | null>(
    () =>
      f
        ? {
            ...(f.conversation_provider_id ? { provider_id: f.conversation_provider_id } : {}),
            conversation_model: f.conversation_model,
            extraction_model: f.extraction_model,
            language: f.language,
            calls: Math.max(1, contactCount),
          }
        : null,
    [f?.conversation_provider_id, f?.conversation_model, f?.extraction_model, f?.language, contactCount], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const estimate = useEstimate(estimateRequest);

  const blockers = useMemo<Blocker[]>(() => {
    if (!f) return [];
    const list: Blocker[] = [];
    if (!f.name.trim() || !f.goal.trim()) {
      list.push({ id: "basics", level: "block", title: !f.name.trim() ? "The campaign has no name" : "The campaign has no goal", detail: "The goal is the agent's brief.", fix: { label: "Add it", step: "basics" } });
    }
    if (health && !health.can_place_calls) {
      list.push({
        id: "telephony",
        level: "block",
        title: "No telephony connected",
        detail: "Calls can't reach real phones yet. Rehearsals in the test lab still work.",
        fix: { label: "Set up Twilio", to: "/app/integrations?tab=telephony" },
      });
    }
    const noProvider = prov.unavailable ? !!health && !health.can_run_simulations : !!prov.providers && !prov.providers.some((p) => p.enabled);
    if (noProvider) {
      list.push({
        id: "provider",
        level: "block",
        title: "No model provider",
        detail: "Nothing can talk until an LLM is connected.",
        fix: prov.unavailable ? { label: "Open AI models", to: "/app/ai-models" } : { label: "Add a provider", action: () => setAddProvider(true) },
      });
    }
    if (contactCount === 0) {
      list.push({ id: "contacts", level: "block", title: "No contacts", detail: "Upload or paste the people to call.", fix: { label: "Add contacts", step: "contacts" } });
    }
    if (f.calling_days.length === 0 || f.calling_hours_end <= f.calling_hours_start) {
      list.push({ id: "window", level: "block", title: "The calling window is empty", fix: { label: "Fix the schedule", step: "schedule" } });
    }
    if (f.precall_enabled) {
      const ok = f.precall_channel === "whatsapp" ? health?.checks.whatsapp : health?.checks.sms;
      if (health && !ok) {
        list.push({
          id: "precall",
          level: "block",
          title: `The heads-up needs ${f.precall_channel === "whatsapp" ? "WhatsApp" : "SMS"}, which isn't set up`,
          detail: "Turn the heads-up off, or set the channel up.",
          fix: { label: "Set it up", to: "/app/integrations?tab=messaging" },
        });
      }
    }
    const unknown = unknownPlaceholders(f.greeting);
    if (unknown.length) {
      list.push({ id: "placeholders", level: "warn", title: "The opening line has unknown placeholders", detail: `${unknown.map((p) => `{${p}}`).join(", ")} would be read aloud.`, fix: { label: "Edit it", step: "agent" } });
    }
    if ((f.mcp_tools?.length ?? 0) > 0 && health?.provider_supports_tools === false) {
      list.push({ id: "tools", level: "warn", title: "The model can't use tools", detail: "Calls still run, without them. Pick a provider that supports tools.", fix: { label: "Change model", step: "agent" } });
    }
    const outside = outsideWindow(f.calling_days, f.calling_hours_start, f.calling_hours_end);
    if (outside && f.calling_days.length && f.calling_hours_end > f.calling_hours_start) {
      list.push({ id: "outside", level: "warn", title: "Outside calling hours right now", detail: `${outside} Launching now queues calls until then.`, fix: { label: "Change hours", step: "schedule" } });
    }
    return list;
  }, [f, health, prov.unavailable, prov.providers, contactCount]);

  /** Create or update, then import any new contacts. */
  const persist = async (): Promise<Campaign> => {
    if (!draft || !base) throw new Error("Nothing to save yet.");
    const payload = payloadOf(draft);
    let saved: Campaign;
    if (mode === "new") {
      saved = await api.createCampaign(payload);
    } else {
      const before = payloadOf(base) as unknown as Record<string, unknown>;
      const changed = Object.fromEntries(
        Object.entries(payload).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(before[k])),
      ) as Partial<CampaignCreate>;
      saved = Object.keys(changed).length ? await api.updateCampaign(id!, changed) : campaign!;
    }
    if (draft.contacts.length) {
      const result = await api.addContacts(saved.id, draft.contacts);
      const skipped = result.skipped_suppressed + result.skipped_duplicate;
      toast.success(`${result.created} contacts imported`, skipped ? `${skipped} skipped (duplicates or do-not-call).` : undefined);
      saved = await api.campaign(saved.id);
    }
    return saved;
  };

  const needsNameGoal = !f?.name.trim() || !f?.goal.trim();

  const saveDraft = async () => {
    if (needsNameGoal) {
      toast.error("Add a name and a goal first", "They're the minimum a draft needs.");
      goTo("basics");
      return;
    }
    setBusy("save");
    setError(null);
    try {
      const saved = await persist();
      clearAutosave(key);
      if (mode === "new") {
        toast.success("Draft saved", "Nothing dials until you launch.");
        navigate(`/app/campaigns/${saved.id}/edit?step=${step}`, { replace: true });
      } else {
        toast.success("Changes saved", saved.status === "running" ? "Calls placed from now on use them." : undefined);
        campaignQ.setData(saved);
      }
    } catch (err) {
      setError((err as Error).message);
      toast.error("Couldn't save", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const launch = async () => {
    if (blockers.some((b) => b.level === "block")) {
      goTo("review");
      return;
    }
    setBusy("launch");
    setError(null);
    try {
      let saved = await persist();
      clearAutosave(key);
      if (saved.status !== "running") saved = await api.setCampaignStatus(saved.id, "start");
      toast.success(`“${saved.name}” is live`, "Calls go out inside each contact's calling window.");
      navigate(`/app/campaigns/${saved.id}`);
    } catch (err) {
      setError((err as Error).message);
      toast.error("Couldn't launch", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  // The sticky action bar sits where the Ask Samvaad launcher lives; lift it.
  useEffect(() => {
    document.body.dataset.actionBar = "";
    return () => {
      delete document.body.dataset.actionBar;
    };
  }, []);

  // Ctrl/Cmd+S saves.
  const saveRef = useRef(saveDraft);
  saveRef.current = saveDraft;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void saveRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (mode === "edit" && campaignQ.error) {
    return (
      <Page>
        <ErrorNote title="Couldn't open this campaign" message={campaignQ.error} onRetry={campaignQ.reload} />
      </Page>
    );
  }

  if (!draft || !base) {
    return (
      <Page width="wide">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="mt-4 h-8 w-64" />
        <Skeleton className="mt-6 h-10 w-full max-w-3xl rounded-full" />
        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Skeleton className="h-96 rounded-xl" />
          <Skeleton className="hidden h-80 rounded-xl lg:block" />
        </div>
      </Page>
    );
  }

  const ctx: Builder = {
    mode,
    campaign: campaign ?? null,
    draft,
    update,
    setForm,
    providers: prov.providers,
    providersUnavailable: prov.unavailable,
    openAddProvider: () => setAddProvider(true),
    languages: languages.data,
    health,
    estimate,
    contactCount,
    blockers,
    goTo,
  };

  const index = STEPS.findIndex((s) => s.id === step);
  const next = STEPS[index + 1];
  const prev = STEPS[index - 1];
  const blocked = blockers.some((b) => b.level === "block");
  const dirty = !sameDraft(draft, base);
  const running = campaign?.status === "running";
  const launchLabel = running ? "Save changes" : campaign?.status === "paused" ? "Save and resume" : "Launch campaign";

  return (
    <BuilderContext.Provider value={ctx}>
      <Page width="wide" className="!pb-0">
        <PageHeader
          back={mode === "edit" && campaign ? { to: `/app/campaigns/${campaign.id}`, label: campaign.name } : { to: "/app/campaigns", label: "Campaigns" }}
          icon={<IconCampaign size={18} />}
          title={mode === "edit" ? "Edit campaign" : "New campaign"}
          meta={campaign && <StatusBadge status={campaign.status} />}
          description={
            mode === "edit"
              ? "Changes apply to calls placed after you save."
              : handoff?.template
                ? `Starting from the “${handoff.template.name}” template. Everything is editable, and nothing dials until you launch.`
                : "Six short steps. Your work is kept on this device as you go, and nothing dials until you launch."
          }
        />

        <Stepper current={step} />

        {restoredAt && (
          <Callout
            tone="info"
            className="mt-4"
            title="Restored your unsaved changes"
            action={
              <Button size="sm" variant="secondary" onClick={discard}>
                Discard
              </Button>
            }
          >
            From {new Date(restoredAt).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}. Discard to go back to the {mode === "edit" ? "saved campaign" : "empty form"}.
          </Callout>
        )}

        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <div className="min-w-0">
            <AnimatePresence mode="wait" initial={false}>
              <m.div key={step} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={T.base}>
                {step === "basics" && <BasicsStep />}
                {step === "agent" && <AgentStep />}
                {step === "tools" && <ToolsStep />}
                {step === "contacts" && <ContactsStep />}
                {step === "schedule" && <ScheduleStep />}
                {step === "review" && <ReviewStep />}
              </m.div>
            </AnimatePresence>
            {error && (
              <Callout tone="critical" title="Not saved" className="mt-4">
                {error}
              </Callout>
            )}
          </div>
          <aside className="min-w-0 lg:sticky lg:top-6" aria-label="Campaign summary">
            <SummaryRail />
          </aside>
        </div>

        {/* Actions: sticky to the bottom of the page's scroller. While it's mounted,
            body[data-action-bar] lifts the Ask Samvaad launcher above it. */}
        <div className="sticky bottom-0 z-20 -mx-4 mt-6 border-t border-line bg-plane/90 px-4 py-3 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
          <div className="flex items-center gap-2">
            <Button variant="ghost" icon={<IconArrowLeft size={14} />} onClick={() => prev && goTo(prev.id)} disabled={!prev} className="max-sm:!px-2.5">
              <span className="max-sm:sr-only">Back</span>
            </Button>
            <p className="hidden min-w-0 truncate text-xs text-ink-muted md:block" aria-live="polite">
              {dirty ? "Unsaved changes, kept on this device" : mode === "edit" ? "All changes saved" : "Nothing entered yet"}
              {estimate.status === "ready" && estimate.estimate.per_call.total !== null && ` · ≈ ${money(estimate.estimate.per_call.total)} per call`}
            </p>
            <div className="ml-auto flex items-center gap-2">
              {(mode === "new" || !running || step !== "review") && (
                <Button variant="secondary" onClick={saveDraft} loading={busy === "save"} disabled={busy !== null || (mode === "edit" && !dirty)}>
                  {mode === "new" ? (<><span className="max-sm:hidden">Save draft</span><span className="sm:hidden">Save</span></>) : "Save"}
                </Button>
              )}
              {next ? (
                <Button onClick={() => goTo(next.id)} iconRight={<IconArrowRight size={14} />}>
                  <span className="max-sm:hidden">Next: </span>
                  {next.short}
                </Button>
              ) : running ? (
                <Button onClick={saveDraft} loading={busy === "save"} disabled={busy !== null || !dirty}>
                  Save changes
                </Button>
              ) : (
                <Button
                  onClick={launch}
                  loading={busy === "launch"}
                  disabled={busy !== null || blocked}
                  icon={<IconPlay size={13} />}
                  title={blocked ? "Fix the items above first" : undefined}
                  className={cx(blocked && "cursor-not-allowed")}
                >
                  <span className="max-sm:hidden">{launchLabel}</span>
                  <span className="sm:hidden">{running ? "Save" : campaign?.status === "paused" ? "Resume" : "Launch"}</span>
                </Button>
              )}
            </div>
          </div>
        </div>
      </Page>

      <ProviderDrawer
        open={addProvider}
        onClose={() => setAddProvider(false)}
        presets={prov.presets}
        onSaved={(p) => {
          prov.upsert(p);
          // First provider in the workspace: use it here too.
          if (!draft.form.conversation_provider_id && !(prov.providers ?? []).some((x) => x.enabled)) setForm({ conversation_provider_id: p.id });
        }}
        onRemoved={prov.remove}
      />
    </BuilderContext.Provider>
  );
}

/** Null when now is inside the window (in this browser's timezone); else when it opens next. */
function outsideWindow(days: number[], start: number, end: number): string | null {
  const now = new Date();
  const today = ((now.getDay() + 6) % 7) + 1;
  const h = now.getHours();
  if (days.includes(today) && h >= start && h < end) return null;
  for (let offset = 0; offset < 8; offset++) {
    const d = ((today - 1 + offset) % 7) + 1;
    if (!days.includes(d)) continue;
    if (offset === 0 && h >= start) continue;
    const when = offset === 0 ? "today" : offset === 1 ? "tomorrow" : ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][d];
    return `In your timezone the next window opens ${when} at ${hour(start)}.`;
  }
  return null;
}
