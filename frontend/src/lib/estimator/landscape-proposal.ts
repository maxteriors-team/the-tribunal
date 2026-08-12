import {
  FIXTURE_TYPES,
  resolveTierFixtures,
  resolveTierWire,
  type FixtureType,
  type QuotedLandscapeWireGauge,
} from "@/lib/estimator/fixtures";
import type {
  CatalogItemResponse,
  PricingSettings,
  ProposalWizardPayload,
} from "@/types/sales-wizard";

export interface LandscapeWireQuoteInput {
  gauge: 8 | 10 | 12 | 14;
  lengthFeet: number | null;
}

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
  wireRuns: LandscapeWireQuoteInput[];
  selectedTierKey: string | null;
  selectedCarePlanKey: string | null;
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

/** Build all tier quantities so one server preview prices Good/Better/Best together. */
export function buildLandscapeProposalQuantities(
  pricing: PricingSettings,
  catalog: CatalogItemResponse[],
  fixtureCounts: Partial<Record<FixtureType, number>>,
  wireRuns: LandscapeWireQuoteInput[],
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
  wireRuns,
  selectedTierKey,
  selectedCarePlanKey,
  contactId,
  opportunityId,
  serviceLocationId,
  lightingProjectId,
  title,
}: BuildLandscapeProposalPayloadOptions): ProposalWizardPayload {
  const careFixtureCount = FIXTURE_TYPES.reduce(
    (total, fixture) => total + Math.max(0, fixtureCounts[fixture.type] ?? 0),
    0,
  );
  return {
    pricing_source: "price_book",
    contact_id: contactId ?? null,
    opportunity_id: opportunityId ?? null,
    service_location_id: serviceLocationId ?? null,
    lighting_project_id: lightingProjectId ?? null,
    title: title?.trim() || "Landscape lighting proposal",
    categories: ["landscape"],
    quantities: buildLandscapeProposalQuantities(pricing, catalog, fixtureCounts, wireRuns),
    additional_charges: [],
    selected_tier: selectedTierKey,
    care_plan_tier: selectedCarePlanKey,
    care_count_manual: careFixtureCount,
    deposit: pricing.deposit?.enabled
      ? { mode: pricing.deposit.mode, value: pricing.deposit.value }
      : null,
    night_preview: null,
    mockups: [],
  } as ProposalWizardPayload & { lighting_project_id?: string | null };
}
