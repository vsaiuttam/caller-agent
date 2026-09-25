import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, type CampaignTemplate } from "../api";
import { IconCheck, IconClock, IconShield, IconSparkle } from "../components/icons";
import {
  Badge,
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Page,
  PageHeader,
  Segmented,
  Skeleton,
  Tabs,
} from "../components/ui";
import { useAsync, useDocumentTitle } from "../hooks";

export default function Templates() {
  useDocumentTitle("Templates");
  const navigate = useNavigate();
  const catalog = useAsync(() => api.templates());
  const languages = useAsync(() => api.languages());

  const [category, setCategory] = useState("All");
  const [language, setLanguage] = useState("en");
  const [preview, setPreview] = useState<CampaignTemplate | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const categories = useMemo(() => {
    const list = catalog.data?.categories ?? [];
    return list.includes("All") ? list : ["All", ...list];
  }, [catalog.data]);

  const visible = useMemo(() => {
    const all = catalog.data?.templates ?? [];
    return category === "All" ? all : all.filter((t) => t.category === category);
  }, [catalog.data, category]);

  const use = (template: CampaignTemplate) => navigate("/campaigns/new", { state: { template, language } });

  return (
    <Page width="wide">
      <PageHeader
        icon={<IconSparkle size={18} />}
        title="Templates"
        description="Ready-to-run campaigns, written the way you'd brief a person. Pick one, edit anything, then load your contacts."
        actions={
          (languages.data?.length ?? 0) > 1 && (
            <Segmented
              label="Preview language"
              size="sm"
              value={language}
              onChange={setLanguage}
              options={(languages.data ?? []).map((lang) => ({ value: lang.code, label: lang.native_name, title: lang.name }))}
            />
          )
        }
      />

      {catalog.error && (
        <div className="mb-4">
          <ErrorNote message={catalog.error} onRetry={catalog.reload} />
        </div>
      )}

      {catalog.loading ? (
        <>
          <Skeleton className="mb-5 h-10 w-full max-w-lg" />
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-64 rounded-xl" />
            ))}
          </div>
        </>
      ) : (
        <>
          <Tabs
            label="Category"
            className="mb-5"
            value={category}
            onChange={setCategory}
            tabs={categories.map((cat) => ({
              value: cat,
              label: cat,
              count: cat === "All" ? catalog.data?.templates.length : catalog.data?.templates.filter((t) => t.category === cat).length,
            }))}
          />
          {visible.length === 0 ? (
            <Card>
              <EmptyState compact title="Nothing in this category" hint="Try another category, or build a campaign from scratch." />
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {visible.map((template) => (
                <TemplateCard
                  key={template.id}
                  template={template}
                  language={language}
                  onPreview={() => {
                    setPreview(template);
                    setPreviewOpen(true);
                  }}
                  onUse={() => use(template)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* The template stays set after closing so the drawer slides out full. */}
      <Drawer
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        title={preview?.name}
        description={preview?.category}
        footer={
          preview && (
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setPreviewOpen(false)}>
                Close
              </Button>
              <Button onClick={() => use(preview)}>Use this template</Button>
            </div>
          )
        }
      >
        {preview && <TemplatePreview template={preview} language={language} />}
      </Drawer>
    </Page>
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
  return (
    <Card interactive className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-semibold tracking-tight text-ink">{template.name}</h2>
          <Badge tone="neutral" className="mt-1.5">
            {template.category}
          </Badge>
        </div>
        <span className="flex shrink-0 items-center gap-1 text-xs text-ink-muted">
          <IconClock size={13} />
          {template.typical_duration}
        </span>
      </div>

      <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-ink-secondary">{template.description}</p>

      <div className="mt-3 rounded-lg border border-line bg-subtle/50 px-3 py-2.5">
        <Eyebrow>Opens with</Eyebrow>
        <p className="mt-1 line-clamp-3 text-xs italic leading-relaxed text-ink-secondary" dir={language === "ur" ? "rtl" : "ltr"}>
          {greeting}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-ink-muted">
        <span className="flex items-center gap-1">
          <IconCheck size={12} /> {template.fields_to_collect.length} fields
        </span>
        <span className="flex items-center gap-1">
          <IconShield size={12} /> {template.constraints.length} guardrails
        </span>
        {template.scorecard.length > 0 && <span>{template.scorecard.length} scored criteria</span>}
      </div>

      <div className="mt-auto flex gap-2 pt-4">
        <Button size="sm" onClick={onUse}>
          Use template
        </Button>
        <Button size="sm" variant="ghost" onClick={onPreview}>
          Preview
        </Button>
      </div>
    </Card>
  );
}

function TemplatePreview({ template, language }: { template: CampaignTemplate; language: string }) {
  const greeting = template.greetings[language] ?? template.greetings.en;
  return (
    <div className="space-y-6 px-5 py-5">
      <Section title="What this campaign does">
        <p className="text-sm leading-relaxed text-ink-secondary">{template.description}</p>
      </Section>
      <Section title="Goal given to the agent">
        <p className="rounded-lg border border-line bg-subtle/50 px-4 py-3 text-sm leading-relaxed text-ink">{template.goal}</p>
      </Section>
      <Section title="Opening line">
        <p className="rounded-lg border border-line bg-subtle/50 px-4 py-3 text-sm italic leading-relaxed text-ink" dir={language === "ur" ? "rtl" : "ltr"}>
          {greeting}
        </p>
      </Section>
      <Section title={`Collects ${template.fields_to_collect.length} things`}>
        <ul className="space-y-1.5">
          {template.fields_to_collect.map((f) => (
            <li key={f} className="flex gap-2 text-sm text-ink-secondary">
              <IconCheck size={14} className="mt-0.5 shrink-0 text-good" />
              {f}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Guardrails">
        <ul className="space-y-1.5">
          {template.constraints.map((c) => (
            <li key={c} className="flex gap-2 text-sm text-ink-secondary">
              <IconShield size={14} className="mt-0.5 shrink-0 text-critical" />
              {c}
            </li>
          ))}
        </ul>
      </Section>
      {template.scorecard.length > 0 && (
        <Section title="Scorecard">
          <ul className="space-y-2">
            {template.scorecard.map((c) => (
              <li key={c.name} className="rounded-lg border border-line px-3 py-2">
                <p className="flex items-center gap-2 text-sm font-medium text-ink">
                  {c.name}
                  {c.knockout && <Badge tone="critical">Required</Badge>}
                  <span className="tnum ml-auto text-2xs text-ink-muted">weight {c.weight}</span>
                </p>
                {c.description && <p className="mt-0.5 text-xs text-ink-muted">{c.description}</p>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {template.extra_instructions && (
        <Section title="Additional guidance">
          <p className="text-sm leading-relaxed text-ink-secondary">{template.extra_instructions}</p>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <Eyebrow className="mb-2">{title}</Eyebrow>
      {children}
    </section>
  );
}
