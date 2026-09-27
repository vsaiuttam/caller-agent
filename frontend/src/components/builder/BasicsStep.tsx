import { useState } from "react";
import { api, type CampaignTemplate } from "../../api";
import { useAsync } from "../../hooks";
import { IconSparkle } from "../icons";
import { Card, CardHeader, ConfirmDialog, Field, Input, Select, Textarea } from "../ui";
import { useBuilder } from "./context";
import { draftFromTemplate } from "./draft";

export function BasicsStep() {
  const { draft, update, setForm, mode } = useBuilder();
  const f = draft.form;
  const templates = useAsync(() => api.templates(), []);
  const [pending, setPending] = useState<CampaignTemplate | null>(null);

  const apply = (t: CampaignTemplate) => {
    const next = draftFromTemplate(t, f.language in t.greetings ? f.language : "en");
    update({
      form: {
        ...f,
        goal: next.form.goal,
        greeting: next.form.greeting,
        scorecard: next.form.scorecard,
        extra_instructions: next.form.extra_instructions,
        template_id: t.id,
        name: f.name.trim() ? f.name : t.name,
        language: next.form.language,
      },
      fieldsText: next.fieldsText,
      constraintsText: next.constraintsText,
      templateGreetings: t.greetings,
    });
    setPending(null);
  };

  const choose = (id: string) => {
    const t = templates.data?.templates.find((x) => x.id === id);
    if (!t) {
      setForm({ template_id: null });
      update({ templateGreetings: null });
      return;
    }
    const hasBrief = f.goal.trim() || draft.fieldsText.trim() || draft.constraintsText.trim() || f.extra_instructions.trim();
    if (hasBrief) setPending(t);
    else apply(t);
  };

  const categories = templates.data?.categories ?? [];

  return (
    <Card>
      <CardHeader title="Basics" subtitle="What this campaign is for. The goal is the agent's brief, so write it the way you'd brief a new hire." />
      <div className="space-y-5 px-5 py-5">
        <Field label="Campaign name">
          <Input value={f.name} onChange={(e) => setForm({ name: e.target.value })} placeholder="Diwali offer follow-ups, Pune" data-autofocus />
        </Field>

        <Field label="Goal" hint="What the call must accomplish, in one or two sentences.">
          <Textarea
            value={f.goal}
            onChange={(e) => setForm({ goal: e.target.value })}
            placeholder="Confirm the customer still wants their service visit on the booked date. If the time no longer works, agree a new slot."
          />
        </Field>

        {mode === "new" || f.template_id ? (
          <Field
            label="Template"
            optional
            hint={
              <span className="inline-flex items-center gap-1">
                <IconSparkle size={11} /> Fills the goal, opening line, questions and guardrails. Everything stays editable.
              </span>
            }
          >
            <Select value={f.template_id ?? ""} onChange={(e) => choose(e.target.value)} disabled={templates.loading}>
              <option value="">{templates.loading ? "Loading templates…" : "None, I'll write my own"}</option>
              {categories.length
                ? categories.map((cat) => (
                    <optgroup key={cat} label={cat}>
                      {(templates.data?.templates ?? [])
                        .filter((t) => t.category === cat)
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                    </optgroup>
                  ))
                : (templates.data?.templates ?? []).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
            </Select>
          </Field>
        ) : null}
      </div>

      <ConfirmDialog
        open={!!pending}
        onClose={() => setPending(null)}
        onConfirm={() => pending && apply(pending)}
        tone="primary"
        title={`Use “${pending?.name}”?`}
        description="It replaces the goal, opening line, questions, guardrails and scorecard you've written. The name, tools, contacts and schedule stay."
        confirmLabel="Replace with template"
      />
    </Card>
  );
}
