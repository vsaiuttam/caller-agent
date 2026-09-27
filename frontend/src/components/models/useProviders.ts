import { useCallback, useEffect, useState } from "react";
import { api, isMissing, type Provider, type ProviderPreset } from "../../api";

/**
 * The workspace's model providers and the presets they're made from.
 * `unavailable` is true on a backend that predates /api/providers.
 */
export function useProviders() {
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [list, presetList] = await Promise.all([api.providers(), api.providerPresets().catch(() => [])]);
      setProviders(list);
      setPresets(presetList);
      setUnavailable(false);
    } catch (err) {
      if (isMissing(err)) setUnavailable(true);
      else setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const upsert = useCallback(
    (p: Provider) =>
      setProviders((prev) => (prev?.some((x) => x.id === p.id) ? prev.map((x) => (x.id === p.id ? p : x)) : [...(prev ?? []), p])),
    [],
  );
  const remove = useCallback((id: string) => setProviders((prev) => prev?.filter((p) => p.id !== id) ?? null), []);

  return { providers, presets, error, unavailable, loading, reload: load, upsert, remove };
}

/** Enabled providers first, database rows before env rows of the same kind. */
export function usableProviders(list: Provider[] | null): Provider[] {
  return (list ?? []).filter((p) => p.enabled);
}
