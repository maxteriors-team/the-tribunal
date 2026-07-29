// Phone Number Types

import type { LeadSourceType } from "@/lib/api/lead-sources";

export interface PhoneNumberLeadSource {
  id: string;
  name: string;
  source_type: LeadSourceType;
}

export interface PhoneNumberLeadSourceCampaign {
  id: string;
  name: string;
}

export interface PhoneNumber {
  id: string;
  workspace_id: string;
  phone_number: string;
  friendly_name?: string | null;
  provider?: "telnyx" | "mac_relay" | string;
  sms_enabled: boolean;
  voice_enabled: boolean;
  mms_enabled: boolean;
  imessage_enabled?: boolean;
  mac_relay_sender_id?: string | null;
  mac_relay_service?: "imessage" | "sms" | "auto" | string;
  assigned_agent_id?: string | null;
  lead_source_id: string | null;
  lead_source_campaign_id: string | null;
  tracking_label: string | null;
  lead_source: PhoneNumberLeadSource | null;
  lead_source_campaign: PhoneNumberLeadSourceCampaign | null;
  is_active: boolean;
}
