import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type CampaignTemplate } from "../api";
import { IconCheck, IconClock } from "../components/icons";
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  PageWrapper,
  Skeleton,
} from "../components/ui";
import { useAsync } from "../hooks";

export default function Templates() {
  const navigate = useNavigate();
  const catalog = useAsync(() => api.templates());
  const languages = useAsync(() => api.languages());

  const [category, setCategory] = useState("All");
  const [language, setLanguage] = useState("en");
  const [preview, setPreview] = useState<CampaignTemplate | null>(null);

  const visible = useMemo(() => {
    const all = catalog.data?.templates ?? [];
    return category === "All" ? all : all.filter((t) => t.category === category);
  }, [catalog.data, category]);

  const use = (template: CampaignTemplate) => {
    navigate("/campaigns/new", { state: { template, language } });
  };

  return (
    <PageWrapper className="px-3 py-4 sm:px-6 sm:py-5">
      <header className="mb-5">
        <h1 className="text-xl font-bold tracking-tight">Templates</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-muted">
          Ready-to-run campaign presets. Pick one and edit from there.
        </p>
      </header>

      {catalog.error && <ErrorNote message={catalog.error} />}

      {/* Language selector */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-ink-muted">Preview language</span>
        <div className="flex flex-wrap gap-1.5">
          {(languages.data ?? []).map((lang) => (
            <button
              key={lang.code}
              onClick={() => setLanguage(lang.code)}
              className={`ripple rounded-md px-3 py-1.5 text-xs font-medium transition-all duration-200 ${
                language === lang.code
                  ? "bg-brand text-plane"
                  : "border border-white/10 text-ink-secondary hover:border-brand/20 hover:bg-white/5"
              }`}
            >
              {lang.native_name}
            </button>
          ))}
        </div>
      </div>

      {/* Category pills */}
      <div className="mb-5 flex flex-wrap gap-1.5">
        {(catalog.data?.categories ?? []).map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`ripple rounded-md px-3.5 py-1.5 text-xs font-medium transition-all duration-200 ${
              category === cat
                ? "bg-brand text-plane"
                : "border border-white/10 text-ink-secondary hover:border-brand/20 hover:bg-white/5"
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {catalog.loading ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-56 rounded-2xl" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <Card hover={false}>
          <EmptyState
            title="Nothing in this category"
            hint="Try another category, or build a campaign from scratch."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((template) => (
            <TemplateCard
              key={template.id}
              template={template}
              language={language}
              onPreview={() => setPreview(template)}
              onUse={() => use(template)}
            />
          ))}
        </div>
      )}

      {preview && (
        <PreviewDrawer
          template={preview}
          language={language}
          onClose={() => setPreview(null)}
          onUse={() => use(preview)}
        />
      )}
    </PageWrapper>
  );
}

function TemplateCard({
  template,
  language,
  onPreview,
  onUse,
}: {
  template: CampaignTemplate;
  language: string;
  onPreview: () => void;
  onUse: () => void;
}) {
  const greeting = template.greetings[language] ?? template.greetings.en;
  const rtl = language === "ur";

  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold">{template.name}</h3>
          <span className="mt-1 inline-block rounded-lg border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-ink-secondary">
            {template.category}
          </span>
        </div>
        <span className="flex shrink-0 items-center gap-1 text-xs text-ink-muted">
          <IconClock size={13} />
          {template.typical_duration}
        </span>
      </div>

      <p className="mt-3 line-clamp-3 text-xs leading-relaxed text-ink-secondary">
        {template.description}
      </p>

      <div className="mt-3 rounded-xl border border-white/5 bg-white/3 px-3 py-2.5">
        <p className="text-[10px] font-bold uppercase tracking-wider text-ink-muted">
          Opens with
        </p>
        <p
          className="mt-1 line-clamp-3 text-xs leading-relaxed italic text-ink-secondary"
          dir={rtl ? "rtl" : "ltr"}
        >
          {greeting}
        </p>
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-ink-muted">
        <span className="flex items-center gap-1">
          <IconCheck size={12} />
          {template.fields_to_collect.length} fields
        </span>
        <span>·</span>
        <span>{template.constraints.length} guardrails</span>
      </div>

      <div className="mt-4 flex gap-2 border-t border-white/5 pt-4">
        <Button size="sm" onClick={onUse}>
          Use template
        </Button>
        <Button size="sm" variant="secondary" onClick={onPreview}>
          Preview
        </Button>
      </div>
    </Card>
  );
}

function PreviewDrawer({
  template,
  language,
  onClose,
  onUse,
}: {
  template: CampaignTemplate;
  language: string;
  onClose: () => void;
  onUse: () => void;
}) {
  const greeting = template.greetings[language] ?? template.greetings.en;
  const rtl = language === "ur";

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/70"
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-lg overflow-y-auto border-l border-white/10 bg-surface animate-in slide-in-from-right duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-start justify-between gap-4 border-b border-white/5 bg-surface/90 px-6 py-4 backdrop-blur-lg">
          <div>
            <h2 className="font-bold">{template.name}</h2>
            <p className="mt-0.5 text-xs text-ink-muted">{template.category}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-ink-muted transition hover:bg-white/5 hover:text-ink"
            aria-label="Close preview"
          >
            ✕
          </button>
        </div>

        <div className="space-y-5 px-3 py-4 sm:px-6 sm:py-5">
          <Section title="What this campaign does">
            <p className="text-sm leading-relaxed text-ink-secondary">
              {template.description}
            </p>
          </Section>

          <Section title="Goal given to the agent">
            <p className="rounded-xl border border-white/5 bg-white/3 px-4 py-3 text-sm leading-relaxed">
              {template.goal}
            </p>
          </Section>

          <Section title="Opening line">
            <p
              className="rounded-xl border border-white/5 bg-white/3 px-4 py-3 text-sm leading-relaxed italic"
              dir={rtl ? "rtl" : "ltr"}
            >
              {greeting}
            </p>
          </Section>

          <Section title={`Collects ${template.fields_to_collect.length} things`}>
            <ul className="space-y-1.5">
              {template.fields_to_collect.map((f) => (
                <li key={f} className="flex gap-2 text-sm text-ink-secondary">
                  <span className="text-brand">·</span>
                  {f}
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Guardrails">
            <ul className="space-y-1.5">
              {template.constraints.map((c) => (
                <li key={c} className="flex gap-2 text-sm text-ink-secondary">
                  <span className="text-critical">·</span>
                  {c}
                </li>
              ))}
            </ul>
          </Section>

          {template.extra_instructions && (
            <Section title="Additional guidance">
              <p className="text-sm leading-relaxed text-ink-secondary">
                {template.extra_instructions}
              </p>
            </Section>
          )}
        </div>

        <div className="sticky bottom-0 border-t border-white/5 bg-surface/90 px-6 py-4 backdrop-blur-lg">
          <Button onClick={onUse}>Use this template</Button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-ink-muted">
        {title}
      </h3>
      {children}
    </div>
  );
}
