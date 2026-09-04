/** Server-computed, non-contractual monthly-payment estimate. */
export interface FinancingEstimate {
  provider: string;
  plan_number?: string | null;
  terms: number[];
  default_term: number;
  apr: number;
  monthly_payment: number;
  /** JSON object keys are strings even though backend terms are integers. */
  monthly_by_term: Record<string, number>;
  headline?: string | null;
  body?: string | null;
  points?: string[];
  disclaimer: string;
}
