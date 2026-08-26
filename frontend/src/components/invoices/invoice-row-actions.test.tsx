import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InvoicesList } from "@/components/invoices/invoices-list";
import type { Invoice, InvoiceStatus } from "@/types";

const { listMock, recordManualPaymentMock, retryReceiptMock, useWorkspaceIdMock } = vi.hoisted(
  () => ({
    listMock: vi.fn(),
    recordManualPaymentMock: vi.fn(),
    retryReceiptMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/invoices", () => ({
  invoicesApi: {
    list: listMock,
    get: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    send: vi.fn(),
    deliver: vi.fn(),
    recordManualPayment: recordManualPaymentMock,
    retryReceipt: retryReceiptMock,
    void: vi.fn(),
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

function invoice(
  status: InvoiceStatus,
  contactId: number | null = 42,
  overrides: Partial<Invoice> = {},
): Invoice {
  return {
    id: `inv-${status}`,
    workspace_id: "ws-1",
    contact_id: contactId ?? undefined,
    number: `INV-${status}`,
    status,
    subtotal: 100,
    tax_amount: 0,
    discount_amount: 0,
    total: 100,
    amount_paid: status === "paid" ? 100 : 0,
    currency: "USD",
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
    receipt_delivery: { status: "skipped" },
    ...overrides,
  };
}

async function openMenuFor(
  status: InvoiceStatus,
  contactId: number | null = 42,
  overrides: Partial<Invoice> = {},
) {
  useWorkspaceIdMock.mockReturnValue("ws-1");
  recordManualPaymentMock.mockResolvedValue(
    invoice("paid", contactId, {
      amount_paid: 100,
      payment_method: "check",
      receipt_delivery: { status: "pending" },
    }),
  );
  retryReceiptMock.mockResolvedValue(
    invoice(status, contactId, { receipt_delivery: { status: "pending" } }),
  );
  listMock.mockResolvedValue({
    items: [invoice(status, contactId, overrides)],
    total: 1,
    page: 1,
    page_size: 100,
    pages: 1,
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <InvoicesList />
    </QueryClientProvider>,
  );
  const trigger = await screen.findByRole("button", { name: "Actions" });
  await userEvent.click(trigger);
}

describe("invoice row actions", () => {
  it("lets an unsent draft be edited or destroyed", async () => {
    await openMenuFor("draft");

    expect(await screen.findByRole("menuitem", { name: /edit invoice/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /send invoice/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /delete draft/i })).toBeInTheDocument();
  });

  it("offers void instead of delete once the customer has it", async () => {
    await openMenuFor("sent");

    // An issued invoice is an accounting record — voidable, never deletable.
    expect(await screen.findByRole("menuitem", { name: /void invoice/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /delete/i })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /resend invoice/i })).toBeInTheDocument();
  });

  it("keeps a paid invoice's money immutable but still annotatable", async () => {
    await openMenuFor("paid");

    expect(await screen.findByRole("menuitem", { name: /edit notes/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /record payment/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /void/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /delete/i })).not.toBeInTheDocument();
  });

  it("records a custom partial deposit by check", async () => {
    await openMenuFor("sent", 42, { total: 2785, amount_paid: 0 });

    await userEvent.click(await screen.findByRole("menuitem", { name: /record payment/i }));

    const dialog = await screen.findByRole("dialog", { name: /record payment/i });
    expect(dialog).toHaveTextContent("$2,785.00");
    const amount = screen.getByLabelText(/payment amount/i);
    await userEvent.clear(amount);
    await userEvent.type(amount, "500");
    expect(dialog).toHaveTextContent("$2,285.00 due");
    await userEvent.type(screen.getByLabelText(/check number/i), "1042");
    await userEvent.click(screen.getByRole("button", { name: /record check payment/i }));

    await waitFor(() => {
      expect(recordManualPaymentMock).toHaveBeenCalledWith(
        "ws-1",
        "inv-sent",
        expect.objectContaining({
          payment_method: "check",
          amount: 500,
          reference: "1042",
          idempotency_key: expect.any(String),
        }),
      );
    });
  });

  it("records the remaining balance as cash without a check number", async () => {
    await openMenuFor("sent");

    await userEvent.click(await screen.findByRole("menuitem", { name: /record payment/i }));
    await userEvent.click(await screen.findByRole("combobox", { name: /payment method/i }));
    await userEvent.click(await screen.findByRole("option", { name: "Cash" }));

    expect(screen.queryByLabelText(/check number/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /record cash payment/i }));

    await waitFor(() => {
      expect(recordManualPaymentMock).toHaveBeenLastCalledWith(
        "ws-1",
        "inv-sent",
        expect.objectContaining({
          payment_method: "cash",
          amount: 100,
          reference: null,
          idempotency_key: expect.any(String),
        }),
      );
    });
  });

  it("offers texting once there is a customer to text", async () => {
    await openMenuFor("sent");

    expect(await screen.findByRole("menuitem", { name: /text invoice/i })).toBeInTheDocument();
  });

  it("hides texting when the invoice has no bill-to contact", async () => {
    await openMenuFor("sent", null);

    expect(await screen.findByRole("menuitem", { name: /resend invoice/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /text invoice/i })).not.toBeInTheDocument();
  });

  it("never offers receipt retry for a settled invoice without an alert", async () => {
    await openMenuFor("paid");

    expect(await screen.findByRole("menuitem", { name: /edit notes/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /text invoice/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /retry receipt/i })).not.toBeInTheDocument();
  });

  it("shows receipt failure details and queues only an eligible retry", async () => {
    await openMenuFor("paid", 42, {
      receipt_delivery: {
        status: "needs_attention",
        recipient: "ada@example.com",
        timestamp: "2026-08-15T12:05:00Z",
        reason: "Receipt delivery failed after multiple attempts. Retry the receipt.",
      },
    });

    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(
      screen.getByText("Receipt delivery failed after multiple attempts. Retry the receipt."),
    ).toBeInTheDocument();

    await userEvent.click(await screen.findByRole("menuitem", { name: /retry receipt/i }));

    await waitFor(() => expect(retryReceiptMock).toHaveBeenCalledWith("ws-1", "inv-paid"));
  });

  it("asks before destroying a draft, naming which one", async () => {
    await openMenuFor("draft");

    await userEvent.click(await screen.findByRole("menuitem", { name: /delete draft/i }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("INV-draft");
    expect(dialog).toHaveTextContent(/can.t be undone/i);
  });
});
