import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InvoicesList } from "@/components/invoices/invoices-list";
import type { Invoice } from "@/types";

const { listMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
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

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

function invoice(overrides: Partial<Invoice> & { id: string }): Invoice {
  return {
    workspace_id: "ws-1",
    number: "INV-0001",
    status: "sent",
    subtotal: 100,
    tax_amount: 0,
    discount_amount: 0,
    total: 100,
    amount_paid: 0,
    currency: "USD",
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
    ...overrides,
  } as Invoice;
}

async function renderList(invoices: Invoice[]) {
  useWorkspaceIdMock.mockReturnValue("ws-1");
  listMock.mockResolvedValue({
    items: invoices,
    total: invoices.length,
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
  await screen.findByRole("table");
}

/** The row containing a given invoice number, so assertions can't cross rows. */
function rowFor(number: string) {
  return screen.getByRole("cell", { name: number }).closest("tr") as HTMLElement;
}

describe("invoice list customer column", () => {
  it("names the customer on the row, not just the invoice number", async () => {
    await renderList([
      invoice({
        id: "inv-1",
        number: "INV-0001",
        contact_id: 42,
        contact_name: "Dana Reyes",
      }),
    ]);

    expect(
      screen.getByRole("columnheader", { name: "Customer" })
    ).toBeInTheDocument();
    expect(
      within(rowFor("INV-0001")).getByText("Dana Reyes")
    ).toBeInTheDocument();
  });

  it("says an invoice has no customer instead of leaving a blank cell", async () => {
    // A blank cell reads as a loading failure; an unattached draft is a real,
    // legitimate state and should say so.
    await renderList([
      invoice({ id: "inv-2", number: "INV-0002", contact_name: null }),
    ]);

    expect(
      within(rowFor("INV-0002")).getByText("No customer")
    ).toBeInTheDocument();
  });

  it("keeps each customer on their own row", async () => {
    await renderList([
      invoice({
        id: "inv-1",
        number: "INV-0001",
        contact_id: 42,
        contact_name: "Dana Reyes",
      }),
      invoice({
        id: "inv-2",
        number: "INV-0002",
        contact_id: 43,
        contact_name: "Sam Ortiz",
      }),
    ]);

    expect(
      within(rowFor("INV-0001")).getByText("Dana Reyes")
    ).toBeInTheDocument();
    expect(
      within(rowFor("INV-0002")).getByText("Sam Ortiz")
    ).toBeInTheDocument();
    // The names must not be duplicated into the wrong row.
    expect(
      within(rowFor("INV-0001")).queryByText("Sam Ortiz")
    ).not.toBeInTheDocument();
  });
});
