// Roofline estimator + permanent-vs-temporary comparison types.
// Sourced from the generated OpenAPI schemas so they stay in lockstep with
// `backend/app/schemas/estimate.py`.

import type { components } from "@/lib/api/_generated";

type Schemas = components["schemas"];

export type LinearFeetEstimateRequest = Schemas["LinearFeetEstimateRequest"];
export type LinearFeetEstimateResult = Schemas["LinearFeetEstimateResult"];
// A standalone rep-entered line (a bucket-truck fee, a one-off custom install)
// that rides on top of a side's total, independent of any Good/Better/Best
// package. `EstimateCustomLineCost` is the same line with the server's amount.
export type EstimateCustomLine = Schemas["EstimateCustomLine"];
export type EstimateCustomLineCost = Schemas["EstimateCustomLineCost"];
// Convert a measured estimate into a real draft quote (the design->quote step).
export type EstimateQuoteRequest = Schemas["EstimateQuoteRequest"];
export type QuoteDetailResponse = Schemas["QuoteDetailResponse"];
export type ComparisonShareRequest = Schemas["ComparisonShareRequest"];
export type ComparisonShareResult = Schemas["ComparisonShareResult"];
export type ComparisonDeliverRequest = Schemas["ComparisonDeliverRequest"];
export type ComparisonDeliverResult = Schemas["ComparisonDeliverResult"];
export type EstimateRenderRequest = Schemas["EstimateRenderRequest"];
export type EstimateRenderResult = Schemas["EstimateRenderResult"];
export type PublicComparison = Schemas["PublicComparison"];
// One seasonal Good/Better/Best package as the client sees it (feet-free: total
// only, never the roofline breakdown). Present on the public comparison payload
// when the workspace sells Christmas packages.
export type PublicComparisonPackage = Schemas["PublicComparisonPackage"];

// Standardized seasonal decor catalog (trees/bushes/wreaths/garland/…).
export type SeasonalItem = Schemas["SeasonalItem"];
export type SeasonalItemCost = Schemas["SeasonalItemCost"];
export type SizeRate = Schemas["SizeRate"];
// One priced Good/Better/Best seasonal package (a tier card + its computed price).
// Present on the rep estimate result when the workspace sells Christmas packages.
export type ChristmasPackagePricing = Schemas["ChristmasPackagePricing"];
// Decor selection: category key -> { option key -> value } (count or feet).
export type ChristmasItemsSelection = Record<string, Record<string, number>>;
