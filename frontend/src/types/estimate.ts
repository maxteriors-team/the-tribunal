// Roofline estimator + permanent-vs-temporary comparison types.
// Sourced from the generated OpenAPI schemas so they stay in lockstep with
// `backend/app/schemas/estimate.py`.

import type { components } from "@/lib/api/_generated";

type Schemas = components["schemas"];

export type LinearFeetEstimateRequest = Schemas["LinearFeetEstimateRequest"];
export type LinearFeetEstimateResult = Schemas["LinearFeetEstimateResult"];
export type ComparisonShareRequest = Schemas["ComparisonShareRequest"];
export type ComparisonShareResult = Schemas["ComparisonShareResult"];
export type ComparisonDeliverRequest = Schemas["ComparisonDeliverRequest"];
export type ComparisonDeliverResult = Schemas["ComparisonDeliverResult"];
export type PublicComparison = Schemas["PublicComparison"];

// Standardized seasonal decor catalog (trees/bushes/wreaths/garland/…).
export type SeasonalItem = Schemas["SeasonalItem"];
export type SeasonalItemCost = Schemas["SeasonalItemCost"];
export type SizeRate = Schemas["SizeRate"];
// One priced Good/Better/Best seasonal package (a tier card + its computed price).
// Present on the rep estimate result when the workspace sells Christmas packages.
export type ChristmasPackagePricing = Schemas["ChristmasPackagePricing"];
// Decor selection: category key -> { option key -> value } (count or feet).
export type ChristmasItemsSelection = Record<string, Record<string, number>>;
