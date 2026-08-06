import { apiGet, apiPost } from "@/lib/api";
import type { PublicCardSetup, PublicCardSetupIntent } from "@/types/card-setup";

// Public card-on-file setup API (no auth — keyed on a single-use, 72-hour token).
export const publicCardSetupApi = {
  get: (token: string): Promise<PublicCardSetup> =>
    apiGet<PublicCardSetup>(`/api/v1/p/card-setup/${token}`),

  // Creates the SetupIntent the browser confirms the card against, and spends
  // the token. `accept_terms` is `Literal[True]` server-side, so a request
  // without consent is rejected before any Stripe object exists.
  // `mandate_text_version` is echoed back so a page left open across a copy
  // change cannot record consent to wording the customer never saw.
  createIntent: (
    token: string,
    mandateTextVersion: string
  ): Promise<PublicCardSetupIntent> =>
    apiPost<PublicCardSetupIntent>(`/api/v1/p/card-setup/${token}/intent`, {
      accept_terms: true,
      mandate_text_version: mandateTextVersion,
    }),
};
