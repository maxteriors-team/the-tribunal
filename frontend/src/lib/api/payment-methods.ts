import { apiDelete, apiGet, apiPost } from "@/lib/api";
import type {
  CardSetupLink,
  ChargeCardRequest,
  ChargeCardResult,
  PaymentMethod,
} from "@/types/payment-method";

const basePath = (workspaceId: string, contactId: number): string =>
  `/api/v1/workspaces/${workspaceId}/contacts/${contactId}/payment-methods`;

// Operator-side card-on-file API. There is deliberately no endpoint that accepts
// card details: the customer types their own card on the tokenized public page.
export const paymentMethodsApi = {
  list: (workspaceId: string, contactId: number): Promise<PaymentMethod[]> =>
    apiGet<PaymentMethod[]>(basePath(workspaceId, contactId)),

  // Mints a single-use 72-hour link and invalidates any earlier unused one, so
  // "send it again" never leaves two live card-entry URLs for one customer.
  createSetupLink: (
    workspaceId: string,
    contactId: number
  ): Promise<CardSetupLink> =>
    apiPost<CardSetupLink>(`${basePath(workspaceId, contactId)}/setup-link`),

  setDefault: (
    workspaceId: string,
    contactId: number,
    paymentMethodId: string
  ): Promise<PaymentMethod> =>
    apiPost<PaymentMethod>(
      `${basePath(workspaceId, contactId)}/${paymentMethodId}/default`
    ),

  // Detaches at Stripe and marks the card removed here. A soft delete: charge
  // attempts still reference it, and those are the record of money taken.
  remove: (
    workspaceId: string,
    contactId: number,
    paymentMethodId: string
  ): Promise<PaymentMethod> =>
    apiDelete<PaymentMethod>(
      `${basePath(workspaceId, contactId)}/${paymentMethodId}`
    ),

  // Resolves rather than throws for a declined card — read `status`, not the
  // absence of an exception.
  charge: (
    workspaceId: string,
    contactId: number,
    payload: ChargeCardRequest
  ): Promise<ChargeCardResult> =>
    apiPost<ChargeCardResult>(
      `${basePath(workspaceId, contactId)}/charge`,
      payload
    ),
};
