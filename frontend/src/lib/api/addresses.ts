import { apiGet, apiPost } from "@/lib/api";

/** Which upstream answered. `none` means no provider is available at all. */
export type AddressProvider = "google_places" | "census" | "none";

/** A resolved address, field-for-field with the contact address columns. */
export interface AddressParts {
  address_line1: string;
  address_line2: string;
  address_city: string;
  address_state: string;
  address_zip: string;
}

export interface AddressSuggestion {
  id: string;
  label: string;
  description: string;
  /**
   * Present when the provider returned a structured address with the candidate
   * list. When it is `null` the suggestion has to be resolved before it can
   * fill a form.
   */
  parts: AddressParts | null;
}

export interface AddressSuggestionsResponse {
  provider: AddressProvider;
  suggestions: AddressSuggestion[];
}

export const addressesApi = {
  suggest: async (
    workspaceId: string,
    query: string,
    sessionToken?: string,
  ): Promise<AddressSuggestionsResponse> => {
    const params = new URLSearchParams({ q: query });
    if (sessionToken) params.set("session_token", sessionToken);
    return apiGet<AddressSuggestionsResponse>(
      `/api/v1/workspaces/${workspaceId}/addresses/suggest?${params.toString()}`,
    );
  },

  resolve: async (
    workspaceId: string,
    suggestionId: string,
    sessionToken?: string,
  ): Promise<AddressParts> => {
    return apiPost<AddressParts>(`/api/v1/workspaces/${workspaceId}/addresses/resolve`, {
      suggestion_id: suggestionId,
      session_token: sessionToken ?? null,
    });
  },
};
