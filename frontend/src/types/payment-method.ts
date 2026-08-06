/**
 * Cards a contact has authorized the workspace to keep and reuse.
 *
 * These are display metadata plus opaque Stripe handles. No type in this file
 * has a field that could carry a card number, and none ever should — the PAN is
 * typed into a Stripe-owned iframe on the public setup page and never crosses
 * this API boundary.
 */

export type PaymentMethodStatus = "active" | "removed" | "expired";

export type ChargeTrigger =
  | "invoice"
  | "deposit"
  | "recurring_job"
  | "no_show_fee"
  | "manual";

/**
 * The three outcomes that must never be blurred together, plus the two
 * "we didn't try" results.
 *
 * - `succeeded` — money moved.
 * - `requires_action` — the customer must authenticate. Recoverable; a
 *   `recovery_url` comes back with it.
 * - `declined` — a hard no. Recorded, the operator is told, and **no retry is
 *   scheduled**.
 * - `error` — we never learned the answer; the webhook reconciles it.
 * - `no_card_on_file` / `skipped_no_automation` — nothing was attempted.
 */
export type ChargeOutcome =
  | "succeeded"
  | "declined"
  | "requires_action"
  | "error"
  | "no_card_on_file"
  | "skipped_no_automation";

export interface PaymentMethod {
  id: string;
  contact_id: number;
  brand?: string | null;
  last4?: string | null;
  exp_month?: number | null;
  exp_year?: number | null;
  is_default: boolean;
  status: PaymentMethodStatus;
  /** Which version of the consent wording this customer agreed to, and when. */
  mandate_text_version: string;
  mandate_accepted_at: string;
  created_at: string;
}

export interface CardSetupLink {
  url: string;
  token: string;
  expires_at: string;
}

export interface ChargeCardRequest {
  amount: number;
  currency?: string;
  description: string;
  trigger?: ChargeTrigger;
  invoice_id?: string | null;
  payment_method_id?: string | null;
}

export interface ChargeCardResult {
  status: ChargeOutcome;
  amount: number;
  currency: string;
  attempt_id?: string | null;
  payment_intent_id?: string | null;
  decline_code?: string | null;
  message?: string | null;
  /** Where to send the customer to authenticate. Never a client secret. */
  recovery_url?: string | null;
}
