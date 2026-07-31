import { describe, expect, it } from "vitest";

import type { InvoiceSendResult } from "@/types";

import { describeInvoiceDelivery } from "./invoice-delivery";

function sendResult(
  overrides: Partial<InvoiceSendResult> = {}
): InvoiceSendResult {
  return {
    id: "inv-1",
    workspace_id: "ws-1",
    number: "INV-000001",
    status: "sent",
    subtotal: 200,
    tax_amount: 0,
    discount_amount: 0,
    total: 200,
    amount_paid: 0,
    currency: "USD",
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
    delivery: "emailed",
    delivered_to: "customer@example.com",
    ...overrides,
  };
}

describe("describeInvoiceDelivery", () => {
  it("celebrates a real delivery and names the recipient", () => {
    const notice = describeInvoiceDelivery(sendResult());

    expect(notice.tone).toBe("success");
    expect(notice.message).toContain("INV-000001");
    expect(notice.message).toContain("customer@example.com");
  });

  it("warns — never congratulates — when the customer has no email", () => {
    const notice = describeInvoiceDelivery(
      sendResult({ delivery: "skipped_no_email", delivered_to: null })
    );

    expect(notice.tone).toBe("warning");
    expect(notice.message).toContain("not emailed");
    expect(notice.description).toContain("Add one");
  });

  it("warns when the provider rejected the send", () => {
    const notice = describeInvoiceDelivery(
      sendResult({ delivery: "failed", delivered_to: null })
    );

    expect(notice.tone).toBe("warning");
    expect(notice.description).toContain("has not received it");
  });
});
