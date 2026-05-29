// Phone Number Types

export interface PhoneNumber {
  id: string;
  workspace_id: string;
  phone_number: string;
  friendly_name?: string;
  provider?: "telnyx" | "mac_relay" | string;
  sms_enabled: boolean;
  voice_enabled: boolean;
  mms_enabled: boolean;
  imessage_enabled?: boolean;
  mac_relay_sender_id?: string | null;
  mac_relay_service?: "imessage" | "sms" | "auto" | string;
  assigned_agent_id?: string;
  is_active: boolean;
}
