// Contact types
import type { MessageDirection } from "./conversation";
import type { Tag } from "./tag";

export type ContactStatus = "new" | "contacted" | "qualified" | "converted" | "lost";

export type EnrichmentStatus = "pending" | "enriched" | "failed" | "skipped";

export interface SocialLinks {
  linkedin?: string | null;
  facebook?: string | null;
  twitter?: string | null;
  instagram?: string | null;
  youtube?: string | null;
  tiktok?: string | null;
}

export interface WebsiteMeta {
  title?: string | null;
  description?: string | null;
}

export interface WebsiteSummary {
  business_description?: string | null;
  services?: string[];
  target_market?: string | null;
  unique_selling_points?: string[];
  industry?: string | null;
  team_size_estimate?: string;
  years_in_business?: number | null;
  service_areas?: string[];
  revenue_signals?: string[];
  has_financing?: boolean;
  certifications?: string[];
}

export interface GooglePlacesData {
  place_id: string;
  rating?: number | null;
  review_count?: number;
  types?: string[];
  business_status?: string;
}

export interface AdPixels {
  meta_pixel?: boolean;
  google_ads?: boolean;
  google_analytics?: boolean;
  gtm?: boolean;
  linkedin_pixel?: boolean;
  tiktok_pixel?: boolean;
}

export interface BusinessIntel {
  social_links?: SocialLinks;
  google_places?: GooglePlacesData;
  website_meta?: WebsiteMeta;
  website_summary?: WebsiteSummary;
  ad_pixels?: AdPixels;
  enrichment_error?: string;
  enrichment_failed_at?: string;
}

export interface Contact {
  id: number;
  user_id: number;
  workspace_id?: string;
  first_name: string;
  last_name?: string;
  email?: string;
  phone_number?: string;
  company_name?: string;
  avatar_url?: string | null;
  status: ContactStatus;
  tags?: string[] | string;
  tag_objects?: Tag[];
  notes?: string;
  /** Legacy free-text import/source label; never used as structured attribution. */
  source?: string | null;
  first_touch_lead_source_id?: string | null;
  first_touch_lead_source_campaign_id?: string | null;
  first_touch_at?: string | null;
  latest_touch_lead_source_id?: string | null;
  latest_touch_lead_source_campaign_id?: string | null;
  latest_touch_at?: string | null;
  attribution_confidence?: number | null;
  lead_source_raw_answer?: string | null;
  created_at: string;
  updated_at: string;
  // Conversation metadata (from list endpoint)
  unread_count?: number;
  last_message_at?: string;
  last_message_direction?: MessageDirection;
  // AI Enrichment fields
  website_url?: string;
  linkedin_url?: string;
  business_intel?: BusinessIntel;
  enrichment_status?: EnrichmentStatus;
  enriched_at?: string;
  lead_score?: number;
  last_engaged_at?: string | null;
  engagement_score?: number;
  noshow_count?: number;
  last_appointment_status?: string | null;
  address_line1?: string;
  address_line2?: string;
  address_city?: string;
  address_state?: string;
  address_zip?: string;
  important_dates?: {
    birthday?: string;
    anniversary?: string;
    custom?: Array<{ label: string; date: string }>;
  } | null;
}
