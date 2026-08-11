import { apiGet, apiPost } from "@/lib/api";
import type {
  PublicInvoice,
  PublicInvoicePaymentCheckout,
  PublicInvoicePaymentStatus,
} from "@/types/public-invoice";

// Public customer invoice API (no auth required — keyed on the share token).
export const publicInvoicesApi = {
  get: (token: string): Promise<PublicInvoice> =>
    apiGet<PublicInvoice>(`/api/v1/p/invoices/${token}`),

  // Start a Stripe Checkout Session for the outstanding balance. Only optional
  // row IDs cross the boundary; the server validates them and prices every row.
  pay: (
    token: string,
    selectedOptionalLineItemIds: string[],
  ): Promise<PublicInvoicePaymentCheckout> =>
    apiPost<PublicInvoicePaymentCheckout>(`/api/v1/p/invoices/${token}/pay`, {
      selected_optional_line_item_ids: selectedOptionalLineItemIds,
    }),

  // Reconcile against Stripe on return from checkout (webhook backstop).
  // Records the payment if Stripe confirms it; safe to call repeatedly.
  paymentStatus: (token: string): Promise<PublicInvoicePaymentStatus> =>
    apiPost<PublicInvoicePaymentStatus>(`/api/v1/p/invoices/${token}/payment-status`),
};
