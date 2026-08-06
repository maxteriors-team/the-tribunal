/**
 * "Charge card on file" from the invoice list.
 *
 * The point of these tests is that the three outcomes stay distinct in the UI.
 * A declined card comes back as a **200 with `status: "declined"`**, not an HTTP
 * error — so a UI that only branches on try/catch would cheerfully report a
 * failed charge as a success. That is the bug being pinned here.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InvoicesList } from "@/components/invoices/invoices-list";
import type { Invoice } from "@/types";
import type { ChargeCardResult } from "@/types/payment-method";

const { listMock, chargeMock, useWorkspaceIdMock, toasts } = vi.hoisted(() => ({
  listMock: vi.fn(),
  chargeMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  toasts: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/lib/api/invoices", () => ({
  invoicesApi: {
    list: listMock,
    get: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    send: vi.fn(),
    deliver: vi.fn(),
    void: vi.fn(),
  },
}));

vi.mock("@/lib/api/payment-methods", () => ({
  paymentMethodsApi: { charge: chargeMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({ toast: toasts }));

function invoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: "inv-1",
    workspace_id: "ws-1",
    contact_id: 42,
    number: "INV-000001",
    status: "sent",
    subtotal: 250,
    tax_amount: 0,
    discount_amount: 0,
    total: 250,
    amount_paid: 0,
    currency: "USD",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  } as Invoice;
}

async function openMenu(subject: Invoice = invoice()) {
  useWorkspaceIdMock.mockReturnValue("ws-1");
  listMock.mockResolvedValue({
    items: [subject],
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
    </QueryClientProvider>
  );
  await userEvent.click(await screen.findByRole("button", { name: "Actions" }));
}

async function confirmCharge(result: ChargeCardResult, subject?: Invoice) {
  chargeMock.mockResolvedValue(result);
  await openMenu(subject);
  await userEvent.click(
    await screen.findByRole("menuitem", { name: /charge card on file/i })
  );
  await userEvent.click(await screen.findByRole("button", { name: /^charge card$/i }));
}

describe("charging a card on file from an invoice", () => {
  it("confirms with the amount before taking any money", async () => {
    chargeMock.mockReset();
    await openMenu();

    await userEvent.click(
      await screen.findByRole("menuitem", { name: /charge card on file/i })
    );

    expect(
      await screen.findByText(/Charge \$250\.00 to the card on file\?/i)
    ).toBeInTheDocument();
    // Says the thing an operator most needs to know before pressing it.
    expect(
      screen.getByText(/without them being present/i)
    ).toBeInTheDocument();
    expect(chargeMock).not.toHaveBeenCalled();
  });

  it("charges the outstanding balance, not the invoice total", async () => {
    chargeMock.mockReset();
    toasts.success.mockReset();

    await confirmCharge(
      {
        status: "succeeded",
        amount: 100,
        currency: "USD",
        attempt_id: "att-1",
        payment_intent_id: "pi_1",
      },
      invoice({ total: 250, amount_paid: 150, status: "partial" })
    );

    await waitFor(() => expect(chargeMock).toHaveBeenCalledTimes(1));
    expect(chargeMock).toHaveBeenCalledWith("ws-1", 42, {
      amount: 100,
      currency: "USD",
      description: "Invoice INV-000001",
      trigger: "invoice",
      invoice_id: "inv-1",
    });
    expect(toasts.success).toHaveBeenCalledWith(
      expect.stringContaining("$100.00"),
      expect.anything()
    );
  });

  it("reports a decline as a failure, with its reason and no retry promised", async () => {
    chargeMock.mockReset();
    toasts.success.mockReset();
    toasts.error.mockReset();

    // A decline is a 200 response, not a thrown error.
    await confirmCharge({
      status: "declined",
      amount: 250,
      currency: "USD",
      attempt_id: "att-2",
      decline_code: "insufficient_funds",
      message: "Your card has insufficient funds.",
    });

    await waitFor(() => expect(toasts.error).toHaveBeenCalled());
    expect(toasts.error).toHaveBeenCalledWith(
      "The card was declined",
      expect.objectContaining({
        description: expect.stringContaining("insufficient_funds"),
      })
    );
    expect(toasts.error.mock.calls[0][1].description).toMatch(/no retry/i);
    // Critically: not reported as a success.
    expect(toasts.success).not.toHaveBeenCalled();
  });

  it("treats needs-authentication as recoverable, not as a decline", async () => {
    chargeMock.mockReset();
    toasts.error.mockReset();
    toasts.warning.mockReset();

    await confirmCharge({
      status: "requires_action",
      amount: 250,
      currency: "USD",
      attempt_id: "att-3",
      payment_intent_id: "pi_auth",
      recovery_url: "https://app.example.com/p/invoices/tok_1",
    });

    await waitFor(() => expect(toasts.warning).toHaveBeenCalled());
    expect(toasts.warning).toHaveBeenCalledWith(
      expect.stringMatching(/approve this payment/i),
      expect.objectContaining({
        description: expect.stringContaining(
          "https://app.example.com/p/invoices/tok_1"
        ),
      })
    );
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it("names the fix when the customer has no card saved", async () => {
    chargeMock.mockReset();
    toasts.warning.mockReset();

    await confirmCharge({
      status: "no_card_on_file",
      amount: 250,
      currency: "USD",
      message: "No card on file for this contact.",
    });

    await waitFor(() => expect(toasts.warning).toHaveBeenCalled());
    expect(toasts.warning).toHaveBeenCalledWith(
      "No card on file for this customer",
      expect.objectContaining({
        description: expect.stringContaining("card-on-file link"),
      })
    );
  });

  it("does not offer to charge an invoice with nothing owed", async () => {
    chargeMock.mockReset();
    await openMenu(invoice({ status: "paid", amount_paid: 250 }));

    expect(
      await screen.findByRole("menuitem", { name: /edit notes/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /charge card on file/i })
    ).not.toBeInTheDocument();
  });

  it("does not offer to charge an invoice with no bill-to contact", async () => {
    chargeMock.mockReset();
    await openMenu(invoice({ contact_id: undefined }));

    expect(
      await screen.findByRole("menuitem", { name: /resend invoice/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /charge card on file/i })
    ).not.toBeInTheDocument();
  });
});
