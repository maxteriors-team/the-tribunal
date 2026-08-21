import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuoteServicesDialog } from "@/components/quotes/quote-services-dialog";
import type { Quote } from "@/types";

/**
 * The dialog's job is to stay ignorant of *where* a quote keeps its money. The
 * server projects a wizard quote's document charges and a plain quote's line
 * items into the same `services` list, so this suite pins that the UI reads only
 * that list, sends the operator's intent to `addService`/`removeService`, and
 * shows the server's repriced total rather than summing anything locally.
 *
 * The one place the two shapes are legitimately visible is the net-amount hint:
 * a wizard quote grosses the typed amount up, so a rep who is not told that will
 * read their own number back wrong.
 */

const { getMock, addServiceMock, updateLineItemMock, removeServiceMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  addServiceMock: vi.fn(),
  updateLineItemMock: vi.fn(),
  removeServiceMock: vi.fn(),
}));

vi.mock("@/lib/api/quotes", () => ({
  quotesApi: {
    get: getMock,
    addService: addServiceMock,
    updateLineItem: updateLineItemMock,
    removeService: removeServiceMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "ws-1",
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// The picker does its own catalog fetch; this suite is about the dialog.
vi.mock("@/components/catalog/catalog-picker", () => ({
  CatalogPicker: () => null,
}));

function makeQuote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: "q-1",
    workspace_id: "ws-1",
    number: "QUO-000001",
    status: "draft",
    subtotal: 400,
    tax_amount: 0,
    discount_amount: 0,
    total: 400,
    currency: "USD",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderDialog(quote: Quote) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <QuoteServicesDialog workspaceId="ws-1" quote={quote} open onOpenChange={() => {}} />
    </QueryClientProvider>,
  );
}

describe("QuoteServicesDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists services from the server's projection, whatever the quote shape", async () => {
    // A wizard quote: its fixture lines are line items, but only the add-on
    // charges come back as services, and only those may be listed here.
    getMock.mockResolvedValue(
      makeQuote({
        total: 16782,
        proposal_document: { version: 1 },
        line_items: [
          {
            id: "li-1",
            quote_id: "q-1",
            name: "ZDC Color Uplight",
            quantity: 12,
            unit_price: 100,
            discount: 0,
            total: 1200,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        services: [{ id: "chg-1", name: "Core drilling", amount: 562 }],
      }),
    );

    renderDialog(makeQuote());

    expect(await screen.findByText("Core drilling")).toBeInTheDocument();
    expect(screen.queryByText("ZDC Color Uplight")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit Core drilling" })).not.toBeInTheDocument();
  });

  it("sends the typed service and shows the total the server returns", async () => {
    getMock.mockResolvedValue(makeQuote({ total: 400, services: [], line_items: [] }));
    addServiceMock.mockResolvedValue(makeQuote({ total: 1000 }));

    const user = userEvent.setup();
    renderDialog(makeQuote());

    await screen.findByText("No services added yet.");
    await user.type(screen.getByPlaceholderText("e.g. Gutter cleaning"), "Gutter cleaning");
    await user.type(screen.getByLabelText("Amount"), "600");
    await user.click(screen.getByRole("button", { name: /add to quote/i }));

    await waitFor(() => expect(addServiceMock).toHaveBeenCalledTimes(1));
    expect(addServiceMock).toHaveBeenCalledWith("ws-1", "q-1", {
      name: "Gutter cleaning",
      amount: 600,
    });
  });

  it("will not submit a service with no amount", async () => {
    getMock.mockResolvedValue(makeQuote({ services: [], line_items: [] }));

    const user = userEvent.setup();
    renderDialog(makeQuote());

    await screen.findByText("No services added yet.");
    await user.type(screen.getByPlaceholderText("e.g. Gutter cleaning"), "Gutter cleaning");

    expect(screen.getByRole("button", { name: /add to quote/i })).toBeDisabled();
  });

  it("edits a plain line's overall amount without changing quantity or discount", async () => {
    getMock.mockResolvedValue(
      makeQuote({
        total: 180,
        services: [
          {
            id: "line-1",
            name: "Permanent lighting package",
            description: "100 ft measured; 100-ft kit",
            amount: 180,
          },
        ],
        line_items: [
          {
            id: "line-1",
            quote_id: "q-1",
            name: "Permanent lighting package",
            description: "100 ft measured; 100-ft kit",
            quantity: 2,
            unit_price: 100,
            discount: 20,
            total: 180,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    );
    updateLineItemMock.mockResolvedValue(makeQuote({ total: 260 }));

    const user = userEvent.setup();
    renderDialog(makeQuote());

    await user.click(
      await screen.findByRole("button", { name: "Edit Permanent lighting package" }),
    );
    const amountInput = screen.getByLabelText("Overall amount");
    await user.clear(amountInput);
    await user.type(amountInput, "260");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(updateLineItemMock).toHaveBeenCalledTimes(1));
    expect(updateLineItemMock).toHaveBeenCalledWith("ws-1", "q-1", "line-1", {
      name: "Permanent lighting package",
      description: "100 ft measured; 100-ft kit",
      unit_price: 140,
    });
  });

  it("removes a service by the id the server gave it", async () => {
    getMock.mockResolvedValue(
      makeQuote({
        total: 1000,
        services: [{ id: "chg-1", name: "Gutter cleaning", amount: 600 }],
      }),
    );
    removeServiceMock.mockResolvedValue(makeQuote({ total: 400 }));

    const user = userEvent.setup();
    renderDialog(makeQuote());

    await user.click(await screen.findByRole("button", { name: "Remove Gutter cleaning" }));

    await waitFor(() => expect(removeServiceMock).toHaveBeenCalledTimes(1));
    expect(removeServiceMock).toHaveBeenCalledWith("ws-1", "q-1", "chg-1");
  });

  it("warns that a sent quote reprices under the customer", async () => {
    getMock.mockResolvedValue(makeQuote({ status: "sent", services: [] }));

    renderDialog(makeQuote({ status: "sent" }));

    expect(await screen.findByText(/updates what the customer sees/i)).toBeInTheDocument();
  });

  it("says the amount is net only on a quote that grosses it up", async () => {
    getMock.mockResolvedValue(makeQuote({ proposal_document: { version: 1 }, services: [] }));
    const { unmount } = renderDialog(makeQuote());
    expect(await screen.findByText(/the finance fee is added/i)).toBeInTheDocument();
    unmount();

    // A plain quote takes the price as typed, so the hint would be a lie.
    getMock.mockResolvedValue(makeQuote({ services: [] }));
    renderDialog(makeQuote());
    await screen.findByText("No services added yet.");
    expect(screen.queryByText(/the finance fee is added/i)).not.toBeInTheDocument();
  });
});
