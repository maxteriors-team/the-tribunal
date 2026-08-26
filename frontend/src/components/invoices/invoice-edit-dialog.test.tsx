import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InvoiceEditDialog } from "@/components/invoices/invoice-edit-dialog";
import type { Invoice, InvoiceSendResult } from "@/types";

const {
  getMock,
  updateMock,
  sendMock,
  retryReceiptMock,
  useWorkspaceIdMock,
  toastMock,
  onOpenChangeMock,
} = vi.hoisted(() => ({
  getMock: vi.fn(),
  updateMock: vi.fn(),
  sendMock: vi.fn(),
  retryReceiptMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  toastMock: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
  onOpenChangeMock: vi.fn(),
}));

vi.mock("@/lib/api/invoices", () => ({
  invoicesApi: {
    get: getMock,
    update: updateMock,
    send: sendMock,
    retryReceipt: retryReceiptMock,
  },
}));

vi.mock("@/components/catalog/catalog-picker", () => ({
  CatalogPicker: () => null,
}));

vi.mock("sonner", () => ({ toast: toastMock }));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function invoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: "invoice-1",
    workspace_id: "ws-1",
    number: "INV-000123",
    contact_id: 42,
    contact_name: "Ada Customer",
    opportunity_id: null,
    status: "sent",
    subtotal: 175,
    tax_amount: 10,
    discount_amount: 5,
    total: 180,
    currency: "USD",
    amount_paid: 0,
    paid_at: null,
    sent_at: "2026-08-01T12:00:00Z",
    issue_date: "2026-08-01",
    due_date: "2026-08-31",
    notes: "Use the side gate",
    terms: "Due on receipt",
    created_at: "2026-08-01T12:00:00Z",
    updated_at: "2026-08-01T12:00:00Z",
    receipt_delivery: { status: "skipped" },
    line_items: [
      {
        id: "line-1",
        invoice_id: "invoice-1",
        name: "House wash",
        description: "North and south elevations",
        quantity: 2.5,
        unit_price: 80,
        discount: 25,
        total: 175,
        is_optional: true,
        is_selected: true,
        created_at: "2026-08-01T12:00:00Z",
        updated_at: "2026-08-01T12:00:00Z",
      },
    ],
    ...overrides,
  };
}

function sendResult(delivery: InvoiceSendResult["delivery"]): InvoiceSendResult {
  return {
    ...invoice(),
    delivery,
    delivered_to: delivery === "emailed" ? "ada@example.com" : null,
  };
}

function renderDialog(row: Invoice = invoice()) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <InvoiceEditDialog invoice={row} open onOpenChange={onOpenChangeMock} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  getMock.mockResolvedValue(invoice());
  updateMock.mockResolvedValue(invoice());
  sendMock.mockResolvedValue(sendResult("emailed"));
  retryReceiptMock.mockResolvedValue(invoice({ receipt_delivery: { status: "pending" } }));
});

describe("InvoiceEditDialog line replacement", () => {
  it("round-trips every API-supported line field without notifying", async () => {
    renderDialog();

    expect(await screen.findByLabelText("Line item 1 name")).toHaveValue("House wash");
    expect(screen.getByLabelText("Line item 1 description")).toHaveValue(
      "North and south elevations",
    );
    expect(screen.getByLabelText("Line item 1 discount")).toHaveValue(25);
    expect(screen.getByRole("checkbox", { name: "Optional item" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save and resend" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save without notifying" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock).toHaveBeenCalledWith("ws-1", "invoice-1", {
      due_date: "2026-08-31",
      tax_amount: 10,
      discount_amount: 5,
      notes: "Use the side gate",
      terms: "Due on receipt",
      line_items: [
        {
          name: "House wash",
          description: "North and south elevations",
          quantity: 2.5,
          unit_price: 80,
          discount: 25,
          is_optional: true,
        },
      ],
    });
    expect(sendMock).not.toHaveBeenCalled();
    expect(toastMock.success).toHaveBeenCalledWith(
      "Invoice INV-000123 updated without notifying the customer",
    );
  });

  it("shows line discounts before invoice tax and discount in the preview", async () => {
    renderDialog();

    const preview = await screen.findByLabelText("Invoice total preview");
    const previewRows = within(preview);

    expect(previewRows.getByText("Line items").parentElement).toHaveTextContent("$200.00");
    expect(previewRows.getByText("Line discounts").parentElement).toHaveTextContent("−$25.00");
    expect(previewRows.getByText("Subtotal").parentElement).toHaveTextContent("$175.00");
    expect(previewRows.getByText("Tax").parentElement).toHaveTextContent("+$10.00");
    expect(previewRows.getByText("Invoice discount").parentElement).toHaveTextContent("−$5.00");
    expect(previewRows.getByText("Total").parentElement).toHaveTextContent("$180.00");
  });
});

describe("InvoiceEditDialog lifecycle controls", () => {
  it("submits only annotation fields for a paid invoice", async () => {
    const paid = invoice({
      status: "paid",
      amount_paid: 180,
      paid_at: "2026-08-15T12:00:00Z",
    });
    getMock.mockResolvedValue(paid);
    updateMock.mockResolvedValue(paid);

    renderDialog(paid);

    expect(await screen.findByLabelText("Line item 1 name")).toBeDisabled();
    expect(screen.getByText(/Amounts and line items are locked/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Line item 1 description")).toBeDisabled();
    expect(screen.getByLabelText("Line item 1 discount")).toBeDisabled();
    expect(screen.getByLabelText("Tax")).toBeDisabled();
    expect(screen.getByLabelText("Invoice discount")).toBeDisabled();
    expect(screen.getByLabelText("Due date")).toBeEnabled();
    expect(screen.getByLabelText("Notes")).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: "Save without notifying" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][2]).toEqual({
      due_date: "2026-08-31",
      notes: "Use the side gate",
      terms: "Due on receipt",
    });
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("saves before explicitly resending an already-sent invoice", async () => {
    renderDialog();

    await userEvent.click(await screen.findByRole("button", { name: "Save and resend" }));

    await waitFor(() => expect(sendMock).toHaveBeenCalledWith("ws-1", "invoice-1"));
    expect(updateMock.mock.invocationCallOrder[0]).toBeLessThan(
      sendMock.mock.invocationCallOrder[0],
    );
    expect(toastMock.success).toHaveBeenCalledWith(
      "Correction saved. Invoice INV-000123 emailed to ada@example.com",
    );
  });

  it("reports that the correction was saved when delivery returns failed", async () => {
    sendMock.mockResolvedValue(sendResult("failed"));
    renderDialog();

    await userEvent.click(await screen.findByRole("button", { name: "Save and resend" }));

    await waitFor(() =>
      expect(toastMock.warning).toHaveBeenCalledWith(
        "Invoice INV-000123 correction saved, but resend failed",
        { description: "The customer has not received it. Try resending." },
      ),
    );
    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(onOpenChangeMock).toHaveBeenCalledWith(false);
  });

  it("reports saved partial success when the resend request rejects", async () => {
    sendMock.mockRejectedValue(new Error("Email service unavailable"));
    renderDialog();

    await userEvent.click(await screen.findByRole("button", { name: "Save and resend" }));

    await waitFor(() =>
      expect(toastMock.warning).toHaveBeenCalledWith(
        "Invoice INV-000123 correction saved, but resend failed",
        { description: "Email service unavailable" },
      ),
    );
    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(onOpenChangeMock).toHaveBeenCalledWith(false);
  });
});

describe("InvoiceEditDialog receipt delivery", () => {
  it("shows partial and final payment history", async () => {
    const paidByCheck = invoice({
      status: "paid",
      total: 2785,
      amount_paid: 2785,
      paid_at: "2026-08-15T12:00:00Z",
      payment_method: "cash",
      payments: [
        {
          id: "payment-1",
          payment_method: "check",
          amount: 500,
          reference: "1042",
          received_at: "2026-02-01T12:00:00Z",
        },
        {
          id: "payment-2",
          payment_method: "cash",
          amount: 2285,
          received_at: "2026-08-15T12:00:00Z",
        },
      ],
    });
    getMock.mockResolvedValue(paidByCheck);

    renderDialog(paidByCheck);

    const payment = await screen.findByLabelText("Payment history");
    expect(within(payment).getByText("check payment")).toBeInTheDocument();
    expect(within(payment).getByText("cash payment")).toBeInTheDocument();
    expect(within(payment).getByText("$500.00")).toBeInTheDocument();
    expect(within(payment).getByText("$2,285.00")).toBeInTheDocument();
    expect(within(payment).getByText("Check number: 1042")).toBeInTheDocument();
  });

  it("shows a sanitized failure and queues a retry", async () => {
    const failed = invoice({
      status: "paid",
      amount_paid: 180,
      paid_at: "2026-08-15T12:00:00Z",
      receipt_delivery: {
        status: "needs_attention",
        recipient: "ada@example.com",
        timestamp: "2026-08-15T12:05:00Z",
        reason: "Receipt delivery failed after multiple attempts. Retry the receipt.",
      },
    });
    const queued = invoice({
      ...failed,
      receipt_delivery: {
        status: "pending",
        recipient: "ada@example.com",
        timestamp: "2026-08-15T12:10:00Z",
      },
    });
    getMock.mockResolvedValue(failed);
    retryReceiptMock.mockResolvedValue(queued);

    renderDialog(failed);

    const receipt = await screen.findByLabelText("Receipt delivery");
    expect(within(receipt).getByText("Needs attention")).toBeInTheDocument();
    expect(within(receipt).getByText("Recipient: ada@example.com")).toBeInTheDocument();
    expect(
      within(receipt).getByText(
        "Receipt delivery failed after multiple attempts. Retry the receipt.",
      ),
    ).toBeInTheDocument();

    await userEvent.click(within(receipt).getByRole("button", { name: "Retry receipt" }));

    await waitFor(() => expect(retryReceiptMock).toHaveBeenCalledWith("ws-1", "invoice-1"));
    expect(toastMock.success).toHaveBeenCalledWith("Receipt for INV-000123 queued");
  });

  it("does not offer retry for a sent receipt", async () => {
    const sent = invoice({
      receipt_delivery: {
        status: "sent",
        recipient: "ada@example.com",
        timestamp: "2026-08-15T12:05:00Z",
      },
    });
    getMock.mockResolvedValue(sent);

    renderDialog(sent);

    expect(await screen.findByText("Receipt delivery")).toBeInTheDocument();
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry receipt" })).not.toBeInTheDocument();
  });
});
