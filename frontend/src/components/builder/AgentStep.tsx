import { useMemo, useState } from "react";
import { api, isMissing } from "../../api";
import { useAsync } from "../../hooks";
import { IconPlus, IconSparkle } from "../icons";
import { CostChip } from "../models/estimate";
import { ModelPicker } from "../models/ModelPicker";
import { ScorecardEditor } from "../Scorecard";
import { Button, Callout, Card, CardHeader, Field, Select, Skeleton, Textarea, cx, toast } from "../ui";
import { languageName, useBuilder } from "./context";
import { VoicePicker } from "./VoicePicker";
import { greetingPreview, unknownPlaceholders } from "./draft";

export const chipClass = (active: boolean) =>
  cx(
    "h-8 rounded-md px-3 text-xs font-medium transition-colors duration-150",
    active ? "bg-brand text-on-brand" : "border border-line-strong bg-surface text-ink-secondary hover:bg-subtle hover:text-ink",
  );

export function AgentStep() {
  const { draft, update, setForm, languages } = useBuilder();
  const f = draft.form;

  const setLanguage = (code: string) => {
    const templateGreeting = draft.templateGreetings?.[code];
    setForm({ language: code, ...(templateGreeting ? { greeting: templateGreeting } : {}) });
  };

  const unknown = useMemo(() => unknownPlaceholders(f.greeting), [f.greeting]);
  const langLabel = languageName(languages, f.language).split(" · ")[0];
  const [translating, setTranslating] = useState(false);
  const english = f.language === "en" || f.language.startsWith("en-");
  // A template without a greeting for this language: offer to translate.
  const templateMissing = !!draft.templateGreetings && !english && !draft.templateGreetings[f.language];

  const translate = async () => {
    const before = f.greeting;
    setTranslating(true);
    try {
      const text = await api.translate(before, f.language);
      if (!text.trim()) throw new Error("The translation came back empty.");
      setForm({ greeting: text });
      toast.success(`Translated to ${langLabel}`, "Read it through before saving. It's spoken exactly as written.", {
        label: "Undo",
        onClick: () => setForm({ greeting: before }),
      });
    } catch (err) {
      toast.error("Couldn't translate", isMissing(err) ? "Translation needs a server update." : (err as Error).message);
    } finally {
      setTranslating(false);
    }
  };
  const preview = greetingPreview(f.greeting, f.name, draft.contacts[0]?.full_name);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Voice and language" subtitle="The agent speaks this language, and switches if the person replies in another." />
        <div className="space-y-5 px-5 py-5">
          <Field label="Language" group>
            {!languages ? (
              <Skeleton className="h-8 w-72 max-w-full" />
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {languages.map((lang) => (
                  <button
                    key={lang.code}
                    type="button"
                    aria-pressed={f.language === lang.code}
                    onClick={() => setLanguage(lang.code)}
                    className={chipClass(f.language === lang.code)}
                    title={lang.name}
                  >
                    {lang.native_name || lang.name}
                  </button>
                ))}
              </div>
            )}
          </Field>

          <Field label="Voice" group hint={`Speakers for ${langLabel}. Play a sample before choosing.`}>
            <VoicePicker language={f.language} languageLabel={langLabel} value={f.voice ?? null} onChange={(voice) => setForm({ voice })} />
          </Field>

          {templateMissing && (
            <Callout
              tone="info"
              title={`This template has no ${langLabel} opening line`}
              action={
                <Button size="sm" variant="secondary" icon={<IconSparkle size={13} />} loading={translating} onClick={translate}>
                  Translate greeting
                </Button>
              }
            >
              Translate the English one with your default model, then edit it. At call time the saved line is spoken, never re-translated.
            </Callout>
          )}

          <Field
            label="Opening line"
            hint={
              <>
                Placeholders: {"{first_name}"}, {"{full_name}"}, {"{campaign_name}"}. Spoken exactly as saved.
                {!english && !templateMissing && (
                  <>
                    {" "}
                    <button type="button" onClick={translate} disabled={translating} className="font-medium text-brand hover:underline disabled:opacity-50">
                      {translating ? "Translating…" : `Translate to ${langLabel}`}
                    </button>
                  </>
                )}
              </>
            }
          >
            <Textarea className="min-h-16 font-mono text-xs" value={f.greeting} onChange={(e) => setForm({ greeting: e.target.value })} />
          </Field>

          <div className="rounded-lg border border-line bg-subtle/50 px-4 py-3">
            <p className="text-2xs font-medium uppercase tracking-wider text-ink-muted">Agent will say</p>
            <p className="mt-1.5 text-sm italic leading-relaxed text-ink">“{preview}”</p>
            {unknown.length > 0 && (
              <p className="mt-2 text-xs text-critical" role="alert">
                Unknown placeholder{unknown.length > 1 ? "s" : ""}: {unknown.map((p) => `{${p}}`).join(", ")}. These would be read aloud literally.
              </p>
            )}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Instructions" subtitle="Given to the agent as its brief." />
        <div className="space-y-5 px-5 py-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Information to collect" hint="One per line.">
              <Textarea
                className="min-h-28 font-mono text-xs"
                value={draft.fieldsText}
                onChange={(e) => update({ fieldsText: e.target.value })}
                placeholder={"Whether the visit date still works\nPreferred slot if rescheduling\nBest WhatsApp number"}
              />
            </Field>
            <Field label="Guardrails" hint="Things the agent must never do. One per line.">
              <Textarea
                className="min-h-28 font-mono text-xs"
                value={draft.constraintsText}
                onChange={(e) => update({ constraintsText: e.target.value })}
                placeholder={"Never quote a price\nDo not promise refunds\nDo not discuss other customers"}
              />
            </Field>
          </div>
          <Field label="Additional guidance" optional hint="Tone, vocabulary, how to handle common objections.">
            <Textarea
              value={f.extra_instructions}
              onChange={(e) => setForm({ extra_instructions: e.target.value })}
              placeholder="Customers often ask whether the technician calls ahead. They do, about 30 minutes before arriving. Keep it warm and brief."
            />
          </Field>
          <Field label="Scorecard" group hint="What each call is judged on. Turns results into a ranked list instead of a call log.">
            <ScorecardEditor value={f.scorecard} onChange={(next) => setForm({ scorecard: next })} />
          </Field>
        </div>
      </Card>

      <ModelCard />
    </div>
  );
}

function ModelCard() {
  const { draft, setForm, providers, providersUnavailable, openAddProvider, estimate, contactCount } = useBuilder();
  const f = draft.form;
  const usable = (providers ?? []).filter((p) => p.enabled);

  return (
    <Card>
      <CardHeader
        title="Model"
        subtitle="Which LLM talks on the call, and which writes the record afterwards."
        action={
          !providersUnavailable && (
            <Button size="sm" variant="secondary" icon={<IconPlus size={13} />} onClick={openAddProvider}>
              Add provider
            </Button>
          )
        }
      />
      <div className="space-y-4 px-5 py-5">
        {providersUnavailable ? (
          <LegacyModelSelects />
        ) : !providers ? (
          <Skeleton className="h-16 w-full" />
        ) : usable.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line-strong px-4 py-4 text-sm">
            <p className="font-medium text-ink">No model provider connected</p>
            <p className="mt-0.5 text-xs text-ink-muted">Nothing can talk until one is. Add a key without leaving this campaign.</p>
            <Button size="sm" className="mt-3" icon={<IconPlus size={13} />} onClick={openAddProvider}>
              Add provider
            </Button>
          </div>
        ) : (
          <>
            <ModelPicker
              providers={usable}
              providerId={f.conversation_provider_id ?? null}
              model={f.conversation_model}
              role="conversation"
              defaultLabel="Workspace default"
              labels={{ provider: "On the call: provider", model: "Model" }}
              onChange={(next) => setForm({ conversation_provider_id: next.provider_id, conversation_model: next.model })}
            />
            <details className="group rounded-lg border border-line px-4 py-3" open={!!(f.extraction_provider_id || f.extraction_model)}>
              <summary className="cursor-pointer text-xs font-medium text-ink-secondary">After the call (extraction)</summary>
              <div className="mt-3">
                <ModelPicker
                  providers={usable}
                  providerId={f.extraction_provider_id ?? null}
                  model={f.extraction_model}
                  role="extraction"
                  defaultLabel="Workspace default"
                  onChange={(next) => setForm({ extraction_provider_id: next.provider_id, extraction_model: next.model })}
                />
              </div>
            </details>
          </>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <CostChip state={estimate} calls={contactCount} />
        </div>
      </div>
    </Card>
  );
}

/** A backend without /api/providers: pick from its single catalog, as before. */
function LegacyModelSelects() {
  const { draft, setForm } = useBuilder();
  const catalog = useAsync(async () => {
    try {
      return await api.models();
    } catch (err) {
      if (isMissing(err)) return null;
      throw err;
    }
  }, []);
  if (catalog.loading) return <Skeleton className="h-16 w-full" />;
  if (!catalog.data) return <p className="text-xs text-ink-muted">This server uses its configured default model.</p>;
  const c = catalog.data;
  const name = (id: string) => c.models.find((m) => m.id === id)?.name ?? id;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Field label="On the call">
        <Select value={draft.form.conversation_model ?? ""} onChange={(e) => setForm({ conversation_model: e.target.value || null })}>
          <option value="">Default ({name(c.defaults.conversation_model)})</option>
          {c.models
            .filter((m) => m.roles.includes("conversation"))
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
        </Select>
      </Field>
      <Field label="After the call">
        <Select value={draft.form.extraction_model ?? ""} onChange={(e) => setForm({ extraction_model: e.target.value || null })}>
          <option value="">Default ({name(c.defaults.extraction_model)})</option>
          {c.models
            .filter((m) => m.roles.includes("extraction"))
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
        </Select>
      </Field>
    </div>
  );
}
