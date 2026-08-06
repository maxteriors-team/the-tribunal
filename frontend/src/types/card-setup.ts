/**
 * The customer-facing card-setup page, served from a single-use token at
 * `/p/card-setup/[token]`.
 *
 * Mirrors the backend `PublicCardSetup` allowlist: first name only, the
 * business name, the publishable key, and the exact consent wording. No
 * workspace, invoice, or contact record crosses this boundary — whoever holds
 * the link learns nothing about the customer they did not already know.
 */
export interface PublicCardSetup {
  /** First name only. Enough to confirm "this is for you", nothing more. */
  contact_name: string;
  business_name: string;
  /** Served from the API, not a build-time variable, so there is one source of truth. */
  publishable_key: string;
  /** Stored against the saved card, so we know what this customer agreed to. */
  mandate_text_version: string;
  mandate_text: string;
  expires_at: string;
}

export interface PublicCardSetupIntent {
  /**
   * Scoped to this one card entry. Handed straight to Stripe.js and never
   * logged, stored, or put in a URL.
   */
  client_secret: string;
  publishable_key: string;
}
