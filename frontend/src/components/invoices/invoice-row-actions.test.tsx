import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InvoicesList } from "@/components/invoices/invoices-list";
import type { Invoice, InvoiceStatus } from "@/types";

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
    void: vi.fn(),
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

function invoice(status: InvoiceStatus): Invoice {
  return {
    id: `inv-${status}`,
    workspace_id: "ws-1",
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
  } as Invoice;
}

async function openMenuFor(status: InvoiceStatus) {
  useWorkspaceIdMock.mockReturnValue("ws-1");
  listMock.mockResolvedValue({
    items: [invoice(status)],
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
  const trigger = await screen.findByRole("button", { name: "Actions" });
  await userEvent.click(trigger);
}

describe("invoice row actions", () => {
  it("lets an unsent draft be edited or destroyed", async () => {
    await openMenuFor("draft");

    expect(
      await screen.findByRole("menuitem", { name: /edit invoice/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: /send invoice/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: /delete draft/i })
    ).toBeInTheDocument();
  });

  it("offers void instead of delete once the customer has it", async () => {
    await openMenuFor("sent");

    // An issued invoice is an accounting record — voidable, never deletable.
    expect(
      await screen.findByRole("menuitem", { name: /void invoice/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /delete/i })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: /resend invoice/i })
    ).toBeInTheDocument();
  });

  it("keeps a paid invoice's money immutable but still annotatable", async () => {
    await openMenuFor("paid");

    expect(
      await screen.findByRole("menuitem", { name: /edit notes/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /void/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /delete/i })
    ).not.toBeInTheDocument();
  });

  it("asks before destroying a draft, naming which one", async () => {
    await openMenuFor("draft");

    await userEvent.click(
      await screen.findByRole("menuitem", { name: /delete draft/i })
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("INV-draft");
    expect(dialog).toHaveTextContent(/can.t be undone/i);
  });
});
