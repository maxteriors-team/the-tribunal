// Quote (estimate) types. Mirrors the backend `app/schemas/quote.py` contract.

import type { components } from "@/lib/api/_generated";

import type { FinancingEstimate } from "./financing";

export type QuoteStatus = "draft" | "sent" | "approved" | "declined" | "expired";
export type QuotePaymentOption = "cash_check" | "financing";
export type DepositPaymentMethod = "card" | "cash" | "check" | "other";
export type ManualDepositPaymentMethod = Exclude<DepositPaymentMethod, "card">;

export interface QuoteLineItem {
  id: string;
  quote_id: string;
  name: string;
  description?: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  created_at: string;
  updated_at: string;
}

export type AssigneeSummary = components["schemas"]["AssigneeSummary"];
export type PermanentKitSelection = components["schemas"]["PermanentKitSelection"];

export interface Quote {
  id: string;
  workspace_id: string;
  contact_id?: number | null;
  service_location_id?: string | null;
  opportunity_id?: string | null;
  assigned_user_id?: number | null;
  assignee?: AssigneeSummary | null;
  lighting_project_id?: string | null;
  revision_of_quote_id?: string | null;
  revision_root_quote_id?: string | null;
  revision_number?: number;
  proposal_version?: number;
  is_wizard_quote?: boolean;
  wizard_edit_mode?: "update" | "revise" | null;
  number: string;
  title?: string | null;
  status: QuoteStatus;
  payment_option?: QuotePaymentOption | null;
  subtotal: number;
  tax_amount: number;
  discount_amount: number;
  total: number;
  currency: string;
  /** Server-owned estimate only for a new exact Permanent Lighting snapshot. */
  financing?: FinancingEstimate | null;
  /** Optional upfront deposit as a percentage of the total (0–100); null = none. */
  deposit_percentage?: number | null;
  deposit_amount_fixed?: number | null;
  deposit_paid_at?: string | null;
  /** Card is provider-confirmed; offline methods are operator attestations. */
  deposit_payment_method?: DepositPaymentMethod | null;
  /** Authenticated operator who recorded cash/check/other; null for card. */
  deposit_recorded_by_id?: number | null;
  /** Server-computed effective deposit in major units (fixed wins); null = none. */
  deposit_amount?: number | null;
  /** Server-computed: a deposit is owed and not yet paid. */
  deposit_required?: boolean;
  /** Server-confirmed card payment or authenticated offline-payment record. */
  deposit_paid?: boolean;
  issue_date?: string | null;
  expiry_date?: string | null;
  sent_at?: string | null;
  approved_at?: string | null;
  declined_at?: string | null;
  decline_reason?: string | null;
  notes?: string | null;
  terms?: string | null;
  converted_job_id?: string | null;
  converted_invoice_id?: string | null;
  /** First time a client opened the public proposal; null = never opened. */
  first_viewed_at?: string | null;
  /** Most recent client open — the "call them now" signal. */
  last_viewed_at?: string | null;
  /** Throttled visit count (repeat opens inside a short window don't count). */
  view_count?: number;
  /** Client-proposal share token; null until the quote is first sent. */
  public_token?: string | null;
  /** Server-selected permanent-light kits for procurement after approval. */
  selected_permanent_kits?: PermanentKitSelection[];
  created_at: string;
  updated_at: string;
  /** Present on detail responses (get/create/update, line-item + lifecycle ops). */
  line_items?: QuoteLineItem[];
  /**
   * Services an operator may add to or remove from this quote, on detail
   * responses. Not the same list as `line_items`: on a wizard quote these are
   * the add-on charges only, because a tier's fixture lines are priced by the
   * design and can't be changed without rebuilding it.
   */
  services?: QuoteService[];
  /**
   * Customer-facing proposal snapshot. It may hold wizard pricing or only media;
   * use `is_wizard_quote` to choose editing behavior. Detail responses only.
   */
  proposal_document?: Record<string, unknown> | null;
  /** Exact validated proposal input; authenticated detail responses only. */
  proposal_input?: components["schemas"]["ProposalWizardPayload"] | null;
  proposal_input_version?: number | null;
}

/**
 * A service an operator added to an existing quote.
 *
 * Server-projected into one shape from whichever place the quote stores its
 * money — a `proposal_document` add-on charge on a proposal-backed quote, a line
 * item on a plain one — so nothing here has to know which. `id` is whatever
 * `quotesApi.removeService` needs in order to take it off again.
 */
export interface QuoteService {
  id: string;
  name: string;
  description?: string | null;
  amount: number;
}

export interface QuoteServiceInput {
  name: string;
  /** Actual selling price; no financing or commission gross-up is added. */
  amount: number;
  /** Price-book item this came from, so the add registers as an attach. */
  catalog_item_id?: string;
}

export interface QuoteLineItemInput {
  name: string;
  description?: string;
  quantity?: number;
  unit_price: number;
  discount?: number;
}

export interface CreateQuoteRequest {
  contact_id?: number;
  service_location_id?: string;
  opportunity_id?: string;
  title?: string;
  currency?: string;
  tax_amount?: number;
  discount_amount?: number;
  deposit_percentage?: number;
  issue_date?: string;
  expiry_date?: string;
  notes?: string;
  terms?: string;
  line_items?: QuoteLineItemInput[];
}

export interface UpdateQuoteRequest {
  contact_id?: number;
  service_location_id?: string;
  opportunity_id?: string;
  title?: string;
  currency?: string;
  tax_amount?: number;
  discount_amount?: number;
  deposit_percentage?: number;
  issue_date?: string;
  expiry_date?: string;
  notes?: string;
  terms?: string;
}

export type CrewNotificationStatus = "sent" | "partial" | "not_applicable" | "failed";

export interface CrewNotificationResult {
  status: CrewNotificationStatus;
  recipient_count: number;
  sent_count: number;
  failed_count: number;
}

export interface QuoteConvertResult {
  quote: Quote;
  job_id: string | null;
  invoice_id: string | null;
  idempotent_replay: boolean;
  crew_notification: CrewNotificationResult;
}

export interface PermanentProfitabilityScenario {
  payment_option: QuotePaymentOption;
  contract_price: number;
  merchant_fee_rate: number;
  merchant_fee: number;
  sales_commission_rate: number;
  sales_commission: number;
  material_cogs: number;
  contribution_before_labor: number;
  contribution_margin: number;
}

export interface PermanentProfitability {
  quote_id: string;
  currency: string;
  provider: string;
  plan_number: string;
  apr: number;
  term_months: number;
  estimated_monthly_payment: number;
  selected_payment_option?: QuotePaymentOption | null;
  cash_check: PermanentProfitabilityScenario;
  financing: PermanentProfitabilityScenario;
}

/**
 * Outcome of emailing or texting a client their proposal link.
 *
 * Taken from the generated OpenAPI schema rather than hand-mirrored: `to` is the
 * destination the server actually resolved (the wizard snapshot's client, the
 * linked contact, or an explicit override), and telling the rep exactly where it
 * went is the whole point of surfacing the result.
 */
export type QuoteDeliverResult = components["schemas"]["QuoteDeliverResult"];
export type QuoteDeliverChannel = QuoteDeliverResult["channel"];
