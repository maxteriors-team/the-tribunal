// Roofline estimator + permanent-vs-temporary comparison types.
// Sourced from the generated OpenAPI schemas so they stay in lockstep with
// `backend/app/schemas/estimate.py`.

import type { components } from "@/lib/api/_generated";

type Schemas = components["schemas"];

export type LinearFeetEstimateRequest = Schemas["LinearFeetEstimateRequest"];
export type LinearFeetEstimateResult = Schemas["LinearFeetEstimateResult"];
export type ComparisonShareRequest = Schemas["ComparisonShareRequest"];
export type ComparisonShareResult = Schemas["ComparisonShareResult"];
export type PublicComparison = Schemas["PublicComparison"];
