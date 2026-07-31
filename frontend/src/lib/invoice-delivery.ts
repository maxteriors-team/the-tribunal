import type { InvoiceSendResult } from "@/types";

/**
 * How to report an invoice send to the operator.
 *
 * Marking an invoice `sent` and the customer actually receiving it are two
 * different things: an invoice with no bill-to contact still transitions, but
 * reaches nobody. Both send call sites (the invoices list and the create
 * dialog) route through here so a delivery that never happened is never
 * reported as a success.
 */
export interface InvoiceDeliveryNotice {
  tone: "success" | "warning";
  message: string;
  /** Follow-up shown under the message when the send needs operator action. */
  description?: string;
}

export function describeInvoiceDelivery(
  invoice: InvoiceSendResult
): InvoiceDeliveryNotice {
  switch (invoice.delivery) {
    case "emailed":
      return {
        tone: "success",
        message: `Invoice ${invoice.number} emailed to ${
          invoice.delivered_to ?? "the customer"
        }`,
      };
    case "skipped_no_email":
      return {
        tone: "warning",
        message: `Invoice ${invoice.number} marked sent, but not emailed`,
        description:
          "No email address on file for the bill-to contact. Add one, then resend.",
      };
    case "failed":
      return {
        tone: "warning",
        message: `Invoice ${invoice.number} marked sent, but the email failed`,
        description: "The customer has not received it. Try resending.",
      };
  }
}
