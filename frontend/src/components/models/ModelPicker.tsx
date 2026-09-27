/**
 * Provider + model, side by side. Used by the workspace defaults, the cost
 * calculator and the campaign builder, so a model is picked the same way
 * everywhere.
 */

import { useEffect, useState } from "react";
import { api, type ModelRole, type Provider, type ProviderModel } from "../../api";
import { Field, Select } from "../ui";
import { perMillion } from "./meta";

const cache = new Map<string, Promise<ProviderModel[]>>();

/** Models of one provider, fetched once per page load (and again after `invalidateModels`). */
export function modelsOf(providerId: string): Promise<ProviderModel[]> {
  let hit = cache.get(providerId);
  if (!hit) {
    hit = api.providerModels(providerId).catch((err) => {
      cache.delete(providerId);
      throw err;
    });
    cache.set(providerId, hit);
  }
  return hit;
}

export function invalidateModels(providerId?: string) {
  if (providerId) cache.delete(providerId);
  else cache.clear();
}

export function useProviderModels(providerId: string | null | undefined) {
  const [models, setModels] = useState<ProviderModel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!providerId) {
      setModels(null);
      return;
    }
    let cancelled = false;
    setModels(null);
    setError(null);
    modelsOf(providerId)
      .then((list) => !cancelled && setModels(list))
      .catch((err) => !cancelled && setError((err as Error).message));
    return () => {
      cancelled = true;
    };
  }, [providerId]);
  return { models, error };
}

export function ModelPicker({
  providers,
  providerId,
  model,
  onChange,
  role,
  defaultLabel,
  disabled = false,
  labels = { provider: "Provider", model: "Model" },
}: {
  providers: Provider[];
  providerId: string | null;
  model: string | null;
  onChange: (next: { provider_id: string | null; model: string | null }) => void;
  role?: ModelRole;
  /** Offer "Workspace default (…)" as the empty choice, e.g. in a campaign. */
  defaultLabel?: string;
  disabled?: boolean;
  labels?: { provider: string; model: string };
}) {
  const { models, error } = useProviderModels(providerId);
  const usable = (models ?? []).filter((m) => !role || m.roles.length === 0 || m.roles.includes(role));
  const known = !model || usable.some((m) => m.id === model);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Field label={labels.provider}>
        <Select
          value={providerId ?? ""}
          disabled={disabled}
          onChange={(e) => onChange({ provider_id: e.target.value || null, model: null })}
        >
          {defaultLabel !== undefined ? <option value="">{defaultLabel}</option> : !providerId && <option value="">Choose a provider</option>}
          {providers.map((p) => (
            <option key={p.id} value={p.id} disabled={!p.enabled}>
              {p.label}
              {!p.enabled ? " (disabled)" : p.status === "error" ? " (failing)" : ""}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={labels.model} error={error ? "Couldn't list this provider's models." : null}>
        <Select
          value={model ?? ""}
          disabled={disabled || !providerId || !models}
          onChange={(e) => onChange({ provider_id: providerId, model: e.target.value || null })}
        >
          <option value="">{!providerId ? "Provider's default" : models ? "Provider's default model" : "Loading models…"}</option>
          {!known && model && <option value={model}>{model}</option>}
          {usable.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
              {m.input_per_mtok === null && m.output_per_mtok === null ? " · price not set" : ` · ${perMillion(m.input_per_mtok)} / ${perMillion(m.output_per_mtok)}`}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}
