import { createContext, useContext } from "react";
import type { Campaign, CampaignCreate, Health, LanguageOption, Provider } from "../../api";
import type { EstimateState } from "../models/estimate";
import type { Draft, StepId } from "./draft";

export interface Blocker {
  id: string;
  /** Blocks launch; warnings only inform. */
  level: "block" | "warn";
  title: string;
  detail?: string;
  fix: { label: string; step?: StepId; to?: string; action?: () => void };
}

export interface Builder {
  mode: "new" | "edit";
  /** The saved campaign in edit mode. */
  campaign: Campaign | null;
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
  setForm: (patch: Partial<CampaignCreate>) => void;
  providers: Provider[] | null;
  /** The backend predates /api/providers. */
  providersUnavailable: boolean;
  openAddProvider: () => void;
  languages: LanguageOption[] | null;
  health: Health | null;
  estimate: EstimateState;
  /** Saved contacts plus the ones waiting to be imported. */
  contactCount: number;
  blockers: Blocker[];
  goTo: (step: StepId) => void;
}

export const BuilderContext = createContext<Builder | null>(null);

export function useBuilder(): Builder {
  const value = useContext(BuilderContext);
  if (!value) throw new Error("useBuilder outside the campaign builder");
  return value;
}

export function languageName(languages: LanguageOption[] | null, code: string): string {
  const l = languages?.find((x) => x.code === code);
  return l ? (l.native_name && l.native_name !== l.name ? `${l.name} · ${l.native_name}` : l.name) : code.toUpperCase();
}
