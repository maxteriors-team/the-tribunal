// Pre-Booking Campaign Types
//
// A pre-booking campaign is an ordinary SMS campaign with a *pre-booking offer*
// attached: next season's work sold now, at a discount, against a deposit. It is
// deliberately not a new `campaign_type` — the campaign row, the sender, and the
// delivery path are all unchanged; only the offer below rides along with it.
//
// Hand-written to mirror `app/schemas/prebooking.py`. The create payload is
// `extra="forbid"` on the backend, so `PreBookingConfigCreate` must never grow a
// field the API doesn't know about.

/** How a money field reads: a percentage of the job, or a flat amount. */
export type PreBookingAmountType = "percentage" | "fixed";

/**
 * Grading of the runway between launch and the season opening. `late` is not an
 * error — an operator may deliberately run a mid-season fill-the-calendar push —
 * but it is never what pre-booking is for, so it is labelled, not swallowed.
 */
export type PreBookingLeadTimeStatus = "ample" | "tight" | "late";

/** Lifecycle of one contact's claim on a season slot. */
export type PreBookingReservationStatus =
  | "held"
  | "confirmed"
  | "released"
  | "cancelled";

/** Payload for attaching a pre-booking offer to an existing campaign. */
export interface PreBookingConfigCreate {
  service_season_start_month: number;
  service_season_end_month: number;
  service_season_year: number;
  service_description: string;
  incentive_type: PreBookingAmountType;
  incentive_value: number;
  deposit_type: PreBookingAmountType;
  deposit_value: number;
  slot_cap: number;
  hold_hours?: number;
}

/** Partial update of an existing pre-booking offer. */
export type PreBookingConfigUpdate = Partial<PreBookingConfigCreate>;

/** A campaign's pre-booking offer plus its live slot and lead-time state. */
export interface PreBookingConfig {
  id: string;
  workspace_id: string;
  campaign_id: string;
  service_season_start_month: number;
  service_season_end_month: number;
  service_season_year: number;
  service_description: string;
  incentive_type: PreBookingAmountType;
  incentive_value: number;
  deposit_type: PreBookingAmountType;
  deposit_value: number;
  slot_cap: number;
  hold_hours: number;
  slots_held: number;
  slots_confirmed: number;
  scheduled_start?: string | null;
  // Computed server-side; read-only here.
  season_start_date: string;
  season_end_date: string;
  season_label: string;
  slots_remaining: number;
  is_full: boolean;
  lead_time_days: number;
  lead_time_status: PreBookingLeadTimeStatus;
  lead_time_message: string;
  created_at: string;
  updated_at: string;
}

/** Query params shared by the audience preview and the enrol call. */
export interface PreBookingAudienceParams {
  include_past_customers?: boolean;
  include_unsold_quotes?: boolean;
  /**
   * Last season's holiday-lighting customers — the homes that were lit last
   * Christmas. Far narrower than the two flags above, which are "anyone we have
   * ever worked for / quoted", so it is opt-in and defaults to `false` on the
   * server. A renewal push turns the broad two off and this one on.
   */
  include_prior_season_christmas?: boolean;
  /**
   * How far back the seasonal slice reaches, in whole seasons (1–10). `1` is
   * strictly last season; omitted (the default) is every season on record.
   */
  seasons_back?: number | null;
  segment_id?: string;
}

/** Counts behind a pre-booking audience, before anyone is enrolled. */
export interface PreBookingAudiencePreview {
  total: number;
  past_customers: number;
  unsold_quotes: number;
  /**
   * Homes lit in an earlier season. Counted by the server whether or not the
   * slice is selected, so the operator can see the size of the renewal list
   * before aiming at it.
   */
  prior_season_christmas: number;
  excluded_opted_out: number;
  excluded_already_enrolled: number;
}

/** Result of enrolling the warm audience into the campaign. */
export interface PreBookingAudienceEnrollResponse {
  enrolled: number;
  skipped_already_enrolled: number;
  excluded_opted_out: number;
  total_contacts: number;
}

/** One contact's claim on a season slot. */
export interface PreBookingReservation {
  id: string;
  workspace_id: string;
  campaign_id: string;
  config_id: string;
  contact_id: number;
  quote_id: string | null;
  job_id: string | null;
  status: PreBookingReservationStatus;
  target_start_date: string;
  target_end_date: string;
  held_at: string;
  hold_expires_at: string;
  confirmed_at: string | null;
  released_at: string | null;
  release_reason: string | null;
  quoted_total: number | null;
  incentive_amount: number | null;
  deposit_amount: number | null;
  created_at: string;
}

/** Accept the pre-booking offer for one contact. */
export interface PreBookingReserveRequest {
  contact_id: number;
  service_location_id?: string;
  source_quote_id?: string;
  base_amount?: number;
  notes?: string;
}

/** A held slot plus the link the customer pays their deposit through. */
export interface PreBookingReserveResponse {
  reservation: PreBookingReservation;
  quote_id: string;
  quote_number: string;
  proposal_url: string;
  deposit_amount: number;
  slots_remaining: number;
}

/** Schedule a pre-booking campaign to launch on a future date. */
export interface PreBookingLaunchRequest {
  scheduled_start: string;
}

/**
 * Headline pre-booking terms carried on a campaign row. Its presence is what
 * marks a campaign as a pre-booking campaign in lists and on the detail page.
 */
export interface CampaignPreBookingSummary {
  id: string;
  service_description: string;
  service_season_start_month: number;
  service_season_end_month: number;
  service_season_year: number;
  incentive_type: PreBookingAmountType;
  incentive_value: number;
  deposit_type: PreBookingAmountType;
  deposit_value: number;
  slot_cap: number;
}
