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

  // Start a Stripe Checkout Session for the outstanding balance; returns the
  // hosted payment URL for the page to redirect to. The amount is derived
  // server-side from the invoice, never sent from here.
  pay: (token: string): Promise<PublicInvoicePaymentCheckout> =>
    apiPost<PublicInvoicePaymentCheckout>(`/api/v1/p/invoices/${token}/pay`),

  // Reconcile against Stripe on return from checkout (webhook backstop).
  // Records the payment if Stripe confirms it; safe to call repeatedly.
  paymentStatus: (token: string): Promise<PublicInvoicePaymentStatus> =>
    apiPost<PublicInvoicePaymentStatus>(
      `/api/v1/p/invoices/${token}/payment-status`
    ),
};
