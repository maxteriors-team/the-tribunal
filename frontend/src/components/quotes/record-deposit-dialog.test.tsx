import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordDepositDialog } from "@/components/quotes/record-deposit-dialog";
import type { Quote } from "@/types";

const { recordDepositMock, toastMock } = vi.hoisted(() => ({
  recordDepositMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: { recordDeposit: recordDepositMock },
}));
vi.mock("sonner", () => ({ toast: toastMock }));

const dueQuote: Quote = {
  id: "quote-1",
  workspace_id: "ws-1",
  number: "QUO-000123",
  title: "Landscape installation",
  status: "approved",
  subtotal: 500,
  tax_amount: 0,
  discount_amount: 0,
  total: 500,
  currency: "USD",
  deposit_amount: 125,
  deposit_required: true,
  deposit_paid: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function renderDialog(onOpenChange = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <RecordDepositDialog workspaceId="ws-1" quote={dueQuote} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
  return onOpenChange;
}

beforeEach(() => {
  vi.clearAllMocks();
  recordDepositMock.mockResolvedValue({
    ...dueQuote,
    deposit_required: false,
    deposit_paid: true,
    deposit_paid_at: "2026-08-13T14:00:00Z",
    deposit_payment_method: "check",
    deposit_recorded_by_id: 7,
  });
});

describe("RecordDepositDialog", () => {
  it("requires a received-money confirmation and records the selected method", async () => {
    const onOpenChange = renderDialog();

    expect(screen.getByText(/received.*completes the deposit/i)).toBeInTheDocument();
    expect(screen.getByText(/closes any open credit-card checkout link/i)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/^Check/));
    await userEvent.click(screen.getByRole("button", { name: "Record check deposit" }));

    await waitFor(() => expect(recordDepositMock).toHaveBeenCalledWith("ws-1", "quote-1", "check"));
    expect(toastMock.success).toHaveBeenCalledWith("Check deposit recorded");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("reports provider truth when the card checkout completed first", async () => {
    recordDepositMock.mockResolvedValue({
      ...dueQuote,
      deposit_required: false,
      deposit_paid: true,
      deposit_paid_at: "2026-08-13T14:00:00Z",
      deposit_payment_method: "card",
    });
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Record cash deposit" }));

    await waitFor(() =>
      expect(toastMock.success).toHaveBeenCalledWith("Deposit was already paid by credit card"),
    );
  });
});
