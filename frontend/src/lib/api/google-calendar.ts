import { apiDelete, apiGet, apiPost } from "@/lib/api";

export interface GoogleCalendarStatus {
  configured: boolean;
  connected: boolean;
  google_email: string | null;
  calendar_id: string | null;
  connected_at: string | null;
}

export const googleCalendarApi = {
  getStatus: () => apiGet<GoogleCalendarStatus>("/api/v1/integrations/google-calendar/status"),

  authorize: (returnUrl: string) =>
    apiPost<{ authorization_url: string }>("/api/v1/integrations/google-calendar/authorize", {
      return_url: returnUrl,
    }),

  disconnect: () => apiDelete("/api/v1/integrations/google-calendar"),
};
