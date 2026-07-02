/**
 * Shared proposal-document normalization + money formatting.
 *
 * The generated OpenAPI types mark defaulted arrays as optional, and the
 * public proposal endpoint ships the snapshot as an untyped JSON dict.
 * Normalizing through one function gives the wizard *and* the public page a
 * single, fully-populated `WizardDocument` shape to render.
 */
import type {
  BistroPricing,
  CarePlanPricing,
  ProposalCharge,
  ProposalDocument,
  ProposalLine,
  ProposalTierView,
  TierPricing,
  WizardClient,
} from "@/types/sales-wizard";

export interface WizardTierView {
  key: string;
  label: string;
  name: string | null;
  experience: string | null;
  warranty: string | null;
  marker: string | null;
  value_tag: string | null;
  popular: boolean;
  points: string[];
  lines: ProposalLine[];
  pricing: TierPricing;
}

export interface WizardCarePlanView {
  fixture_count: number;
  free_fixtures: number;
  options: CarePlanPricing[];
  selected: string | null;
}

export interface WizardFinancingView {
  enabled: boolean;
  provider: string;
  terms: number[];
  default_term: number;
  max_amount: number;
  headline: string | null;
  body: string | null;
  points: string[];
  disclaimer: string | null;
}

export interface WizardBistroView extends Omit<BistroPricing, "lines"> {
  lines: NonNullable<BistroPricing["lines"]>;
}

export interface WizardDocument {
  client: WizardClient | null;
  tier_order: string[];
  tiers: WizardTierView[];
  selected_tier: string | null;
  headline_tier: string | null;
  additional_charges: ProposalCharge[];
  care_plan: WizardCarePlanView | null;
  bistro: WizardBistroView | null;
  financing: WizardFinancingView | null;
  night_preview: Record<string, unknown> | null;
  selected_financed_total: number;
  selected_cash_total: number;
  selected_monthly_payment: number;
}

export function normalizeDocument(doc: ProposalDocument): WizardDocument {
  return {
    client: doc.client ?? null,
    tier_order: doc.tier_order ?? [],
    tiers: (doc.tiers ?? []).map((tier: ProposalTierView) => ({
      key: tier.key,
      label: tier.label,
      name: tier.name ?? null,
      experience: tier.experience ?? null,
      warranty: tier.warranty ?? null,
      marker: tier.marker ?? null,
      value_tag: tier.value_tag ?? null,
      popular: tier.popular ?? false,
      points: tier.points ?? [],
      lines: tier.lines ?? [],
      pricing: tier.pricing,
    })),
    selected_tier: doc.selected_tier ?? null,
    headline_tier: doc.headline_tier ?? null,
    additional_charges: doc.additional_charges ?? [],
    care_plan: doc.care_plan
      ? {
          fixture_count: doc.care_plan.fixture_count,
          free_fixtures: doc.care_plan.free_fixtures,
          options: doc.care_plan.options ?? [],
          selected: doc.care_plan.selected ?? null,
        }
      : null,
    bistro: doc.bistro
      ? { ...doc.bistro, lines: doc.bistro.lines ?? [] }
      : null,
    financing: doc.financing
      ? {
          enabled: doc.financing.enabled,
          provider: doc.financing.provider,
          terms: doc.financing.terms ?? [],
          default_term: doc.financing.default_term,
          max_amount: doc.financing.max_amount,
          headline: doc.financing.headline ?? null,
          body: doc.financing.body ?? null,
          points: doc.financing.points ?? [],
          disclaimer: doc.financing.disclaimer ?? null,
        }
      : null,
    night_preview:
      (doc.night_preview as Record<string, unknown> | null | undefined) ??
      null,
    selected_financed_total: doc.selected_financed_total ?? 0,
    selected_cash_total: doc.selected_cash_total ?? 0,
    selected_monthly_payment: doc.selected_monthly_payment ?? 0,
  };
}

/**
 * Parse the untyped snapshot dict from the public proposal endpoint.
 * Returns null when the quote has no wizard snapshot (plain quotes).
 */
export function parseProposalDocument(
  raw: Record<string, unknown> | null | undefined,
): WizardDocument | null {
  if (!raw || typeof raw !== "object") return null;
  const doc = raw as unknown as ProposalDocument;
  if (!Array.isArray(doc.tiers) || !doc.tiers.length) return null;
  return normalizeDocument(doc);
}

/** `$1,234` — matches the original wizard's fmt(). */
export function fmt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

/** `$14.86` — per-foot rates keep their cents (original fmt2()). */
export function fmt2(n: number): string {
  return `$${Number(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
