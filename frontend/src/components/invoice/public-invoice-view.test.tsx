import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PublicInvoiceView } from "@/components/invoice/public-invoice-view";
import type { PublicInvoice } from "@/types/public-invoice";

vi.mock("@/lib/api/public-invoices", () => ({
  publicInvoicesApi: { pay: vi.fn(), paymentStatus: vi.fn(), get: vi.fn() },
}));

function invoice(overrides: Partial<PublicInvoice> = {}): PublicInvoice {
  return {
    token: "tok_123",
    number: "INV-000001",
    status: "sent",
    currency: "USD",
    line_items: [
      {
        name: "Gutter cleaning",
        description: "Two-story home",
        quantity: 1,
        unit_price: 485,
        discount: 0,
        total: 485,
      },
    ],
    subtotal: 485,
    tax_amount: 0,
    discount_amount: 0,
    total: 485,
    amount_paid: 0,
    balance_due: 485,
    issue_date: "2026-07-01",
    due_date: "2026-07-15",
    is_paid: false,
    is_void: false,
    is_overdue: false,
    is_payable: true,
    client_name: "Dana Homeowner",
    notes: null,
    terms: null,
    branding: {
      business_name: "Maxteriors Lighting Co.",
      logo_url: null,
      brand_color: "#0F172A",
      accent_color: "#2563EB",
      business_address: null,
      business_phone: "555-0100",
      business_email: null,
      footer: null,
    },
    ...overrides,
  };
}

function renderView(data: PublicInvoice) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PublicInvoiceView data={data} />
    </QueryClientProvider>
  );
}

describe("PublicInvoiceView", () => {
  it("leads with the balance the customer actually owes", () => {
    renderView(invoice());

    // Labelled in the hero and again beside the pay button.
    expect(screen.getAllByText("Balance Due")).toHaveLength(2);
    expect(screen.getAllByText("$485.00").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: /pay now/i })
    ).toBeInTheDocument();
  });

  it("shows a paid deposit as a credit so the balance isn't read as a pricing error", () => {
    renderView(
      invoice({ total: 2000, amount_paid: 500, balance_due: 1500, subtotal: 2000 })
    );

    // The credit line and the resulting balance both have to be present —
    // this is the double-billing bug made visible to the customer.
    expect(screen.getByText("Already paid")).toBeInTheDocument();
    expect(screen.getByText("−$500.00")).toBeInTheDocument();
    expect(screen.getAllByText("$1,500.00").length).toBeGreaterThan(0);
  });

  it("congratulates rather than bills once the invoice is settled", () => {
    renderView(
      invoice({
        status: "paid",
        amount_paid: 485,
        balance_due: 0,
        is_paid: true,
        is_payable: false,
      })
    );

    expect(screen.getByRole("status")).toHaveTextContent(/paid in full/i);
    expect(
      screen.queryByRole("button", { name: /pay now/i })
    ).not.toBeInTheDocument();
  });

  it("tells the customer how to pay instead of showing a dead button", () => {
    // Money is owed but Stripe isn't configured for this business.
    renderView(invoice({ is_payable: false }));

    expect(
      screen.queryByRole("button", { name: /pay now/i })
    ).not.toBeInTheDocument();
    expect(screen.getByText(/get in touch/i)).toBeInTheDocument();
  });

  it("keeps the per-unit detail available when the table collapses on mobile", () => {
    const { container } = renderView(invoice());

    // The narrow-screen meta line must carry qty × unit price, since those
    // columns are hidden below 560px.
    const meta = container.querySelector(".inv-item-meta");
    expect(meta).toHaveTextContent("1 × $485.00");
  });

  it("exposes a table a screen reader can navigate", () => {
    renderView(invoice());

    const table = screen.getByRole("table");
    expect(
      within(table).getByRole("columnheader", { name: "Item" })
    ).toBeInTheDocument();
    expect(table).toHaveAccessibleName(/line items for invoice INV-000001/i);
    expect(
      screen.getByRole("heading", { level: 1, name: /maxteriors/i })
    ).toBeInTheDocument();
  });
});
