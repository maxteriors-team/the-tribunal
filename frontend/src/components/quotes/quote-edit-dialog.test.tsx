/**
 * Editing a quote after it has been sent.
 *
 * The dangerous parts of this dialog are the ones that are invisible when they
 * break: clearing a deposit has to be expressed as 0 (the API treats null as
 * "leave it alone"), and a wizard-priced quote must never have its tax/discount
 * moved from here — the customer's page prices from the stored document, so a
 * header-level reprice would show up on the dashboard and nowhere else. Both
 * are pinned below, along with the fact that the copy tells the operator their
 * edit lands on the link the customer already has.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuoteEditDialog } from "@/components/quotes/quote-edit-dialog";
import type { Quote } from "@/types";

const { getMock, updateMock, useWorkspaceIdMock, toastMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  updateMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: { get: getMock, update: updateMock },
}));

vi.mock("sonner", () => ({ toast: toastMock }));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function quote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: "quote-1",
    workspace_id: "ws-1",
    number: "QUO-000123",
    title: "Backyard lighting install",
    status: "sent",
    subtotal: 1000,
    tax_amount: 70,
    discount_amount: 0,
    total: 1070,
    currency: "USD",
    public_token: "tok-abc",
    notes: "Gate code 4821",
    terms: "50% on approval",
    expiry_date: "2026-09-01",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function renderDialog(row: Quote = quote()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <QuoteEditDialog quote={row} open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  updateMock.mockResolvedValue(quote());
});

describe("QuoteEditDialog on a sent quote", () => {
  it("warns that the edit lands on the customer's existing link", async () => {
    getMock.mockResolvedValue(quote());

    renderDialog();

    expect(await screen.findByText(/link the customer already has/i)).toBeInTheDocument();
  });

  it("calls a draft a draft instead", async () => {
    const draft = quote({ status: "draft", public_token: null });
    getMock.mockResolvedValue(draft);

    renderDialog(draft);

    expect(await screen.findByText(/Update this draft before it goes out/i)).toBeInTheDocument();
  });

  it("saves the header and clears an emptied note with an empty string", async () => {
    // The API skips nulls, so an omitted note would silently keep the old text.
    getMock.mockResolvedValue(quote());

    renderDialog();

    const notes = await screen.findByLabelText("Notes");
    await userEvent.clear(notes);
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    expect(updateMock.mock.calls[0][2]).toMatchObject({ notes: "" });
  });

  it("extends the expiry so a sent quote stops lapsing", async () => {
    getMock.mockResolvedValue(quote());

    renderDialog();

    const expiry = await screen.findByLabelText("Valid until");
    await userEvent.clear(expiry);
    await userEvent.type(expiry, "2026-10-15");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    expect(updateMock.mock.calls[0][2]).toMatchObject({
      expiry_date: "2026-10-15",
    });
  });
});

describe("QuoteEditDialog deposits", () => {
  it("clears a deposit as 0, because null means 'leave it alone'", async () => {
    getMock.mockResolvedValue(quote({ deposit_percentage: 25 }));

    renderDialog();

    await userEvent.click(await screen.findByRole("combobox", { name: "Deposit" }));
    await userEvent.click(await screen.findByRole("option", { name: "No deposit" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    const payload = updateMock.mock.calls[0][2];
    expect(payload).toMatchObject({ deposit_percentage: 0 });
    // Sending the fixed column too would trip the server's "one mode only" rule.
    expect(payload).not.toHaveProperty("deposit_amount_fixed");
  });

  it("sends a fixed deposit on its own column", async () => {
    getMock.mockResolvedValue(quote({ deposit_percentage: 25 }));

    renderDialog();

    await userEvent.click(await screen.findByRole("combobox", { name: "Deposit" }));
    await userEvent.click(await screen.findByRole("option", { name: "Fixed amount" }));
    const amount = screen.getByLabelText("Amount");
    await userEvent.clear(amount);
    await userEvent.type(amount, "300");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    const payload = updateMock.mock.calls[0][2];
    expect(payload).toMatchObject({ deposit_amount_fixed: 300 });
    expect(payload).not.toHaveProperty("deposit_percentage");
  });

  it("says a paid deposit will not be refunded or re-charged", async () => {
    getMock.mockResolvedValue(
      quote({ deposit_percentage: 25, deposit_paid_at: "2026-07-05T00:00:00Z" }),
    );

    renderDialog();

    expect(await screen.findByText(/won.t refund or charge the difference/i)).toBeInTheDocument();
  });
});

describe("QuoteEditDialog and wizard pricing", () => {
  it("never offers to reprice a wizard quote from the header", async () => {
    getMock.mockResolvedValue(quote({ proposal_document: { selected_tier: "better" }, is_wizard_quote: true }));

    renderDialog();

    await screen.findByLabelText("Title");
    expect(screen.queryByLabelText("Tax")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Discount")).not.toBeInTheDocument();
    expect(screen.getByText(/comes from the sales wizard/i)).toBeInTheDocument();
  });

  it("omits tax and discount from a wizard quote's payload", async () => {
    // Belt and braces: even if the fields reappeared, the request must not carry
    // a total the customer's proposal page would never show.
    getMock.mockResolvedValue(quote({ proposal_document: { selected_tier: "better" }, is_wizard_quote: true }));

    renderDialog();

    await screen.findByLabelText("Title");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    const payload = updateMock.mock.calls[0][2];
    expect(payload).not.toHaveProperty("tax_amount");
    expect(payload).not.toHaveProperty("discount_amount");
  });

  it("does let a plain quote move its tax, which is its real price", async () => {
    getMock.mockResolvedValue(
      quote({
        proposal_document: {
          mockups: [{ image: "data:image/jpeg;base64,/9j/2Q==" }],
        },
        is_wizard_quote: false,
      }),
    );

    renderDialog();

    const tax = await screen.findByLabelText("Tax");
    await userEvent.clear(tax);
    await userEvent.type(tax, "85");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    expect(updateMock.mock.calls[0][2]).toMatchObject({ tax_amount: 85 });
  });
});
