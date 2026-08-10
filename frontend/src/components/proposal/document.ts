/**
 * Proposal-document normalization + money formatting for the client view.
 *
 * The public proposal endpoint ships the saved snapshot as an untyped JSON dict
 * and the generated OpenAPI types mark defaulted arrays as optional. Normalizing
 * through one function gives the client proposal view a single, fully-populated
 * `ProposalDoc` shape to render across all product lines (landscape tiers,
 * permanent/christmas/bistro category sections, care plan, financing).
 *
 * Self-contained: imports the contract straight from the generated client so it
 * survives the removal of the old sales-wizard builder.
 */
import type { components } from "@/lib/api/_generated";

type Schemas = components["schemas"];

type ProposalDocument = Schemas["ProposalDocument"];
type ProposalTierView = Schemas["ProposalTierView"];
type ProposalLine = Schemas["ProposalLine"];
type ProposalCharge = Schemas["ProposalCharge"];
type ProposalCategorySection = Schemas["ProposalCategorySection"];
type CategoryLine = Schemas["CategoryLine"];
type TierPricing = Schemas["TierPricing"];
type CarePlanPricing = Schemas["CarePlanPricing"];
type BistroPricing = Schemas["BistroPricing"];
type WizardClient = Schemas["WizardClient"];
type ProposalMockup = Schemas["ProposalMockup"];
export type ProposalValueProp = Schemas["ValueProp"];

/**
 * The service path a quote came from. `christmas` is the only one that changes
 * the page's whole presentation, so it is named rather than inferred at each
 * call site. A quote spanning several service paths is `mixed`, which stays
 * neutral: a landscape package must not arrive wrapped in garland.
 */
export type ProposalService =
  | "landscape"
  | "permanent"
  | "bistro"
  | "christmas"
  | "mixed";

export interface ProposalTier {
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

export interface ProposalCarePlanView {
  fixture_count: number;
  free_fixtures: number;
  options: CarePlanPricing[];
  selected: string | null;
}

export interface ProposalFinancingView {
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

export interface ProposalBistroView extends Omit<BistroPricing, "lines"> {
  lines: NonNullable<BistroPricing["lines"]>;
}

export interface ProposalCategoryView
  extends Omit<ProposalCategorySection, "lines" | "value_props"> {
  lines: CategoryLine[];
  value_props: ProposalValueProp[];
}

/** The fully-normalized proposal snapshot the client view renders. */
export interface ProposalDoc {
  service: ProposalService | null;
  client: WizardClient | null;
  tier_order: string[];
  tiers: ProposalTier[];
  selected_tier: string | null;
  headline_tier: string | null;
  additional_charges: ProposalCharge[];
  care_plan: ProposalCarePlanView | null;
  bistro: ProposalBistroView | null;
  financing: ProposalFinancingView | null;
  night_preview: Record<string, unknown> | null;
  mockups: ProposalMockup[];
  categories: string[];
  category_sections: ProposalCategoryView[];
  selected_financed_total: number;
  selected_cash_total: number;
  selected_monthly_payment: number;
  grand_financed_total: number;
  grand_cash_total: number;
  grand_monthly_payment: number;
}

const SERVICES: readonly ProposalService[] = [
  "landscape",
  "permanent",
  "bistro",
  "christmas",
  "mixed",
];

/**
 * Narrow the snapshot's free-string service to the known set.
 *
 * Snapshots predating the field, and any value a future backend adds, resolve
 * to `null` — which every consumer treats as "present it neutrally". An unknown
 * service must never be guessed into a themed presentation.
 */
function parseService(value: unknown): ProposalService | null {
  return SERVICES.find((s) => s === value) ?? null;
}

export function normalizeProposalDocument(doc: ProposalDocument): ProposalDoc {
  return {
    service: parseService(doc.service),
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
      (doc.night_preview as Record<string, unknown> | null | undefined) ?? null,
    mockups: (doc.mockups ?? []).filter(
      (m): m is ProposalMockup => Boolean(m?.image),
    ),
    categories: doc.categories ?? [],
    category_sections: (doc.category_sections ?? []).map(
      (section: ProposalCategorySection) => ({
        ...section,
        lines: section.lines ?? [],
        // Absent on every snapshot saved before value props existed. Empty is
        // the honest read: render nothing, never an empty promise block.
        value_props: section.value_props ?? [],
      }),
    ),
    selected_financed_total: doc.selected_financed_total ?? 0,
    selected_cash_total: doc.selected_cash_total ?? 0,
    selected_monthly_payment: doc.selected_monthly_payment ?? 0,
    grand_financed_total: doc.grand_financed_total ?? 0,
    grand_cash_total: doc.grand_cash_total ?? 0,
    grand_monthly_payment: doc.grand_monthly_payment ?? 0,
  };
}

/**
 * Parse the untyped snapshot dict from the public proposal endpoint. Returns
 * null when the quote has no priced product line (a plain line-item quote),
 * which the page renders with its simple light sheet instead.
 */
export function parseProposalDocument(
  raw: Record<string, unknown> | null | undefined,
): ProposalDoc | null {
  if (!raw || typeof raw !== "object") return null;
  const doc = raw as unknown as ProposalDocument;
  const hasTiers = Array.isArray(doc.tiers) && doc.tiers.length > 0;
  const hasSections =
    Array.isArray(doc.category_sections) && doc.category_sections.length > 0;
  const hasBistro = Boolean(doc.bistro && (doc.bistro.total ?? 0) > 0);
  if (!hasTiers && !hasSections && !hasBistro) return null;
  return normalizeProposalDocument(doc);
}

/**
 * Whether this proposal should present as Christmas.
 *
 * Drives the festive theme and copy, so it deliberately answers "is Christmas
 * the *whole* job" rather than "does this quote touch Christmas". A mixed quote
 * stays on the neutral premium sheet: wrapping a year-round install in garland
 * misrepresents what the customer is buying.
 */
export function isChristmasProposal(doc: ProposalDoc): boolean {
  if (doc.service) return doc.service === "christmas";
  // Snapshots saved before `service` existed still carry section keys, which is
  // the same signal the server derives it from. Requiring christmas to be the
  // only priced line reproduces the `mixed` exclusion above.
  return (
    doc.tiers.length === 0 &&
    !doc.bistro &&
    doc.category_sections.length > 0 &&
    doc.category_sections.every((section) => section.key === "christmas")
  );
}

/** The selling points to render, in section order. Empty on old snapshots. */
export function proposalValueProps(doc: ProposalDoc): ProposalValueProp[] {
  return doc.category_sections.flatMap((section) => section.value_props);
}

/**
 * Every lit-photo design on the proposal, in the order the rep built them.
 *
 * `night_preview` is opaque JSONB and its shape grew: a design can now span
 * several photos of the same job (front, back, walkway), but snapshots saved
 * before that carry a single `image`. Reading both keeps those proposals
 * rendering their one photo instead of silently going blank.
 */
export function nightImages(
  nightPreview: Record<string, unknown> | null | undefined,
): string[] {
  const many = nightPreview?.images;
  if (Array.isArray(many)) {
    const images = many.filter((img): img is string => typeof img === "string");
    if (images.length) return images;
  }
  const one = nightPreview?.image;
  return typeof one === "string" ? [one] : [];
}

/** `$1,234` — whole-dollar proposal figures. */
export function fmt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `$${Math.round(n).toLocaleString("en-US")}`;
}
