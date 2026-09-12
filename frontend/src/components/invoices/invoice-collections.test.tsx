/**
 * The collections view: what's owed, who's late, and the unpaid filter.
 *
 * `status` goes stale (the server only re-derives it when an invoice is edited),
 * so the row must show server-computed balance and lateness rather than anything
 * inferred from the badge. These tests pin that an invoice reading "sent" still
 * displays as late when the server says it is.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

function invoice(overrides: Partial<Invoice> & { id: string; number: string }): Invoice {
  return {
    workspace_id: "ws-1",
    status: "sent",
    subtotal: 100,
    tax_amount: 0,
    discount_amount: 0,
    total: 100,
    amount_paid: 0,
    balance_due: 100,
    currency: "USD",
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
    ...overrides,
  } as Invoice;
}

async function renderList(invoices: Invoice[], outstandingTotal = 0) {
  useWorkspaceIdMock.mockReturnValue("ws-1");
  listMock.mockResolvedValue({
    items: invoices,
    total: invoices.length,
    page: 1,
    page_size: 100,
    pages: 1,
    outstanding_total: outstandingTotal,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InvoicesList />
    </QueryClientProvider>,
  );
  await screen.findByRole("table");
}

function rowFor(number: string) {
  return screen.getByRole("cell", { name: number }).closest("tr") as HTMLElement;
}

describe("what each row owes", () => {
  it("shows the outstanding balance, not just the total", async () => {
    await renderList([
      invoice({ id: "i1", number: "INV-1", total: 250, amount_paid: 100, balance_due: 150 }),
    ]);

    expect(within(rowFor("INV-1")).getByText("$150.00")).toBeVisible();
  });

  it("shows a dash rather than $0.00 when nothing is owed", async () => {
    await renderList([
      invoice({ id: "i1", number: "INV-1", status: "paid", amount_paid: 100, balance_due: 0 }),
    ]);

    expect(within(rowFor("INV-1")).queryByText("$0.00")).toBeNull();
  });
});

describe("lateness", () => {
  it("flags a late invoice whose stored status still reads sent", async () => {
    await renderList([
      invoice({
        id: "i1",
        number: "INV-1",
        status: "sent",
        due_date: "2026-01-15",
        days_overdue: 30,
      }),
    ]);

    const row = rowFor("INV-1");
    expect(within(row).getByText("30d late")).toBeVisible();
    // The stale badge is still rendered; the lateness marker is what corrects it.
    expect(within(row).getByText("sent")).toBeVisible();
  });

  it("does not flag an invoice that is merely due, not late", async () => {
    await renderList([
      invoice({ id: "i1", number: "INV-1", due_date: "2099-01-15", days_overdue: null }),
    ]);

    expect(within(rowFor("INV-1")).queryByText(/late/)).toBeNull();
  });
});

describe("the unpaid filter", () => {
  it("asks the server for unpaid invoices only", async () => {
    await renderList([invoice({ id: "i1", number: "INV-1" })]);
    listMock.mockClear();

    await userEvent.click(screen.getByLabelText("Unpaid only"));

    await waitFor(() => {
      expect(listMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ unpaid_only: true }),
      );
    });
  });

  it("omits the flag when switched off, rather than sending false", async () => {
    await renderList([invoice({ id: "i1", number: "INV-1" })]);

    expect(listMock).toHaveBeenCalledWith(
      "ws-1",
      expect.objectContaining({ unpaid_only: undefined }),
    );
  });
});

describe("the book-wide total", () => {
  it("reports what is owed across every matching invoice", async () => {
    await renderList([invoice({ id: "i1", number: "INV-1" })], 4210.5);

    expect(screen.getByText("$4,210.50 outstanding")).toBeVisible();
  });

  it("stays quiet when nothing is owed", async () => {
    await renderList([invoice({ id: "i1", number: "INV-1", balance_due: 0 })], 0);

    expect(screen.queryByText(/outstanding/)).toBeNull();
  });
});
