import axios, { AxiosError } from "axios";

import { getBackendUrl } from "@/lib/utils/backend-url";

// Browser calls stay same-origin so the Next rewrite proxies them to the
// backend; SSR needs the absolute origin. Deliberately NOT the shared `api`
// client: its 401 interceptor redirects to /login, which would hijack a
// public page a homeowner is filling in.
const API_URL = typeof window !== "undefined" ? "" : getBackendUrl();

const publicApi = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

/** Mirrors `LeadSubmitRequest` on `POST /api/v1/p/leads/{public_key}`. */
export interface PublicLeadSubmission {
  first_name: string;
  last_name?: string;
  email?: string;
  /** 10 digits or E.164; the backend normalizes and rejects anything else. */
  phone_number: string;
  address?: string;
  notes?: string;
  source_detail?: string;
  landing_page?: string;
  referrer?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
  utm_content?: string;
  utm_term?: string;
  gclid?: string;
  fbclid?: string;
  /** 10DLC/TCR: only true when the optional checkbox was actually ticked. */
  sms_consent?: boolean;
}

export interface PublicLeadResponse {
  success: boolean;
  message: string;
}

function extractErrorMessage(error: unknown): string {
  const detail =
    error instanceof AxiosError ? (error.response?.data as { detail?: unknown } | undefined)?.detail : undefined;
  return typeof detail === "string" ? detail : "Something went wrong. Please try again.";
}

/** Submit a website lead into the CRM. The lead source's `allowed_domains` must include this page's origin. */
export async function submitPublicLead(
  publicKey: string,
  body: PublicLeadSubmission,
): Promise<PublicLeadResponse> {
  try {
    const response = await publicApi.post<PublicLeadResponse>(
      `/api/v1/p/leads/${encodeURIComponent(publicKey)}`,
      body,
    );
    return response.data;
  } catch (error) {
    throw new Error(extractErrorMessage(error));
  }
}
