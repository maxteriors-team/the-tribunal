import {
  FIXTURE_TYPES,
  resolveTierFixtures,
  resolveTierTransformer,
  resolveTierWire,
  type FixtureType,
  type QuotedLandscapeWireGauge,
} from "@/lib/estimator/fixtures";
import type { LandscapeScheduleRow } from "@/lib/estimator/landscape-schedule";
import type {
  CatalogItemResponse,
  PricingSettings,
  ProposalWizardPayload,
  WizardBistroRun,
} from "@/types/sales-wizard";

export interface LandscapeWireQuoteInput {
  gauge: 8 | 10 | 12 | 14;
  lengthFeet: number | null;
}

export interface LandscapeBistroQuoteInput {
  installation: "temporary" | "permanent" | null;
  lengthFeet: number | null;
  poleCount: number;
}

export type GroupedLandscapeBistroRun = WizardBistroRun;

export interface LandscapeProposalLinkage {
  contactId?: number | null;
  opportunityId?: string | null;
  serviceLocationId?: string | null;
  lightingProjectId?: string | null;
  title?: string | null;
}

export interface BuildLandscapeProposalPayloadOptions extends LandscapeProposalLinkage {
  pricing: PricingSettings;
  catalog: CatalogItemResponse[];
  fixtureCounts: Partial<Record<FixtureType, number>>;
  transformerCount: number;
  fixedItems?: Array<{ itemId: string; quantity: number }>;
  wireRuns: LandscapeWireQuoteInput[];
  bistroRuns?: LandscapeBistroQuoteInput[];
  selectedTierKey: string | null;
  selectedCarePlanKey: string | null;
  additionalLineItems?: Array<{ description: string; amount: number }>;
}

function addQuantity(quantities: Map<string, number>, itemId: string | null, quantity: number) {
  if (!itemId || !Number.isFinite(quantity) || quantity <= 0) return;
  // A workspace can reuse one SKU in multiple Good/Better/Best tiers. The
  // proposal engine reads that same quantity for each tier, so never sum it
  // merely because more than one package references it.
  quantities.set(itemId, Math.max(quantities.get(itemId) ?? 0, quantity));
}

export function aggregateWireFeet(
  wireRuns: LandscapeWireQuoteInput[],
): Map<QuotedLandscapeWireGauge, number> {
  const totals = new Map<QuotedLandscapeWireGauge, number>();
  for (const run of wireRuns) {
    if ((run.gauge !== 10 && run.gauge !== 12) || run.lengthFeet === null) continue;
    if (!Number.isFinite(run.lengthFeet) || run.lengthFeet <= 0) continue;
    totals.set(run.gauge, (totals.get(run.gauge) ?? 0) + run.lengthFeet);
  }
  return totals;
}

export function aggregateBistroRuns(
  runs: LandscapeBistroQuoteInput[],
): GroupedLandscapeBistroRun[] {
  const totals = {
    temporary: { feet: 0, pole_count: 0 },
    permanent: { feet: 0, pole_count: 0 },
  };
  for (const run of runs) {
    if (!run.installation || run.lengthFeet === null) continue;
    if (!Number.isFinite(run.lengthFeet) || run.lengthFeet <= 0) continue;
    totals[run.installation].feet += run.lengthFeet;
    totals[run.installation].pole_count += Math.max(0, Math.floor(run.poleCount));
  }
  return (["temporary", "permanent"] as const).flatMap((installation) =>
    totals[installation].feet > 0 ? [{ installation, ...totals[installation] }] : [],
  );
}

export function splitLandscapeFixturePricing(
  rows: readonly Pick<
    LandscapeScheduleRow,
    "fixtureType" | "fixtureCatalogItemId" | "fixtureCatalogItemIsOverride" | "fixtureSku"
  >[],
  totals: Partial<Record<FixtureType, number>>,
): {
  fixtureCounts: Partial<Record<FixtureType, number>>;
  fixedItems: Array<{ itemId: string; quantity: number }>;
} {
  const fixtureCounts = { ...totals };
  const fixed = new Map<string, number>();
  const knownTypes = new Set(FIXTURE_TYPES.map((fixture) => fixture.type));
  for (const row of rows) {
    if (!row.fixtureCatalogItemIsOverride || !row.fixtureCatalogItemId) continue;
    if (!knownTypes.has(row.fixtureType as FixtureType)) continue;
    const fixtureType = row.fixtureType as FixtureType;
    fixtureCounts[fixtureType] = Math.max(0, (fixtureCounts[fixtureType] ?? 0) - 1);
    const itemId = row.fixtureSku?.trim() || row.fixtureCatalogItemId;
    fixed.set(itemId, (fixed.get(itemId) ?? 0) + 1);
  }
  return {
    fixtureCounts,
    fixedItems: [...fixed].map(([itemId, quantity]) => ({ itemId, quantity })),
  };
}

export function hasUnpriceableBistroRuns(runs: LandscapeBistroQuoteInput[]): boolean {
  return runs.some(
    (run) =>
      !run.installation ||
      run.lengthFeet === null ||
      !Number.isFinite(run.lengthFeet) ||
      run.lengthFeet <= 0,
  );
}

/** Build all tier quantities so one server preview prices Good/Better/Best together. */
export function buildLandscapeProposalQuantities(
  pricing: PricingSettings,
  catalog: CatalogItemResponse[],
  fixtureCounts: Partial<Record<FixtureType, number>>,
  wireRuns: LandscapeWireQuoteInput[],
  transformerCount: number,
): ProposalWizardPayload["quantities"] {
  const quantities = new Map<string, number>();
  const tierOrder = pricing.tier_order ?? [];
  const tierKeys = tierOrder.length ? tierOrder : (pricing.tiers ?? []).map((tier) => tier.key);
  const wireFeet = aggregateWireFeet(wireRuns);

  for (const tierKey of tierKeys) {
    const fixtureResolution = resolveTierFixtures(pricing, catalog, tierKey);
    for (const fixture of FIXTURE_TYPES) {
      addQuantity(
        quantities,
        fixtureResolution[fixture.type].itemId,
        fixtureCounts[fixture.type] ?? 0,
      );
    }
    addQuantity(
      quantities,
      resolveTierTransformer(pricing, catalog, tierKey).itemId,
      transformerCount,
    );
    for (const [gauge, feet] of wireFeet) {
      const item = resolveTierWire(pricing, catalog, tierKey, gauge);
      addQuantity(quantities, item?.sku || item?.id || null, feet);
    }
  }

  return [...quantities.entries()].map(([item_id, quantity]) => ({ item_id, quantity }));
}

export function buildLandscapeProposalPayload({
  pricing,
  catalog,
  fixtureCounts,
  transformerCount,
  fixedItems = [],
  wireRuns,
  bistroRuns = [],
  selectedTierKey,
  selectedCarePlanKey,
  additionalLineItems = [],
  contactId,
  opportunityId,
  serviceLocationId,
  lightingProjectId,
  title,
}: BuildLandscapeProposalPayloadOptions): ProposalWizardPayload {
  const careFixtureCount =
    FIXTURE_TYPES.reduce(
      (total, fixture) => total + Math.max(0, fixtureCounts[fixture.type] ?? 0),
      0,
    ) +
    fixedItems.reduce(
      (total, item) => total + (Number.isFinite(item.quantity) ? Math.max(0, item.quantity) : 0),
      0,
    );
  const groupedBistroRuns = aggregateBistroRuns(bistroRuns);
  return {
    pricing_source: "price_book",
    contact_id: contactId ?? null,
    opportunity_id: opportunityId ?? null,
    service_location_id: serviceLocationId ?? null,
    lighting_project_id: lightingProjectId ?? null,
    title: title?.trim() || "Landscape lighting proposal",
    categories: groupedBistroRuns.length ? ["landscape", "bistro"] : ["landscape"],
    quantities: buildLandscapeProposalQuantities(
      pricing,
      catalog,
      fixtureCounts,
      wireRuns,
      transformerCount,
    ),
    fixed_items: fixedItems
      .filter((item) => item.itemId && Number.isFinite(item.quantity) && item.quantity > 0)
      .map((item) => ({ item_id: item.itemId, quantity: item.quantity })),
    bistro: groupedBistroRuns.length
      ? {
          product: "color",
          tier: "easy",
          feet: groupedBistroRuns.reduce((total, run) => total + run.feet, 0),
          runs: groupedBistroRuns,
        }
      : null,
    additional_charges: additionalLineItems
      .map((line) => ({
        description: line.description.trim(),
        net_amount: Number.isFinite(line.amount) ? Math.max(0, line.amount) : 0,
        catalog_item_id: null,
        tier_key: null,
      }))
      .filter((line) => line.description && line.net_amount > 0),
    selected_tier: selectedTierKey,
    customer_can_select_package: true,
    care_plan_tier: selectedCarePlanKey,
    care_count_manual: careFixtureCount,
    deposit: pricing.deposit?.enabled
      ? { mode: pricing.deposit.mode, value: pricing.deposit.value }
      : null,
    night_preview: null,
    mockups: [],
  } as ProposalWizardPayload & { lighting_project_id?: string | null };
}
