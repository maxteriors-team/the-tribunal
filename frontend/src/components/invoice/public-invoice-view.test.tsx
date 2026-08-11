import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublicInvoiceView } from "@/components/invoice/public-invoice-view";
import { publicInvoicesApi } from "@/lib/api/public-invoices";
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
        id: "11111111-1111-4111-8111-111111111111",
        name: "Gutter cleaning",
        description: "Two-story home",
        quantity: 1,
        unit_price: 485,
        discount: 0,
        total: 485,
        is_optional: false,
        is_selected: true,
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
    </QueryClientProvider>,
  );
}

describe("PublicInvoiceView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("leads with the balance the customer actually owes", () => {
    renderView(invoice());

    // Labelled in the hero and again beside the pay button.
    expect(screen.getAllByText("Balance Due")).toHaveLength(2);
    expect(screen.getAllByText("$485.00").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /pay now/i })).toBeInTheDocument();
  });

  it("shows a paid deposit as a credit so the balance isn't read as a pricing error", () => {
    renderView(
      invoice({
        total: 2000,
        amount_paid: 500,
        balance_due: 1500,
        subtotal: 2000,
        line_items: [
          {
            ...invoice().line_items[0],
            unit_price: 2000,
            total: 2000,
          },
        ],
      }),
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
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent(/paid in full/i);
    expect(screen.queryByRole("button", { name: /pay now/i })).not.toBeInTheDocument();
  });

  it("tells the customer how to pay instead of showing a dead button", () => {
    // Money is owed but Stripe isn't configured for this business.
    renderView(invoice({ is_payable: false }));

    expect(screen.queryByRole("button", { name: /pay now/i })).not.toBeInTheDocument();
    expect(screen.getByText(/get in touch/i)).toBeInTheDocument();
  });

  it("keeps the per-unit detail available when the table collapses on mobile", () => {
    const { container } = renderView(invoice());

    // The narrow-screen meta line must carry qty × unit price, since those
    // columns are hidden below 560px.
    const meta = container.querySelector(".inv-item-meta");
    expect(meta).toHaveTextContent("1 × $485.00");
  });

  it("carries the workspace logo, like the proposal that preceded it", () => {
    renderView(
      invoice({
        branding: {
          ...invoice().branding,
          logo_url: "https://cdn.example.com/logo.png",
        },
      }),
    );

    // A customer who approved a branded proposal must not receive an unbranded
    // invoice — the two documents are the same relationship.
    const logo = screen.getByAltText("Maxteriors Lighting Co.");
    expect(logo).toHaveAttribute("src", "https://cdn.example.com/logo.png");
  });

  it("renders no logo slot when the workspace has not uploaded one", () => {
    renderView(invoice());

    expect(screen.queryByAltText("Maxteriors Lighting Co.")).not.toBeInTheDocument();
  });

  it("updates subtotal, total, and balance when an optional item is removed", async () => {
    const user = userEvent.setup();
    renderView(
      invoice({
        line_items: [
          {
            ...invoice().line_items[0],
            unit_price: 100,
            total: 100,
          },
          {
            id: "22222222-2222-4222-8222-222222222222",
            name: "Downspout flush",
            description: null,
            quantity: 1,
            unit_price: 40,
            discount: 0,
            total: 40,
            is_optional: true,
            is_selected: true,
          },
        ],
        subtotal: 140,
        tax_amount: 10,
        discount_amount: 5,
        total: 145,
        balance_due: 145,
      }),
    );

    const checkbox = screen.getByRole("checkbox", { name: "Include Downspout flush" });
    expect(checkbox).toBeChecked();
    await user.click(checkbox);

    expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent(
      "0 of 1 optional item included. Current total: $105.00.",
    );
    const totals = document.querySelector(".pq-totals");
    expect(totals).not.toBeNull();
    expect(within(totals as HTMLElement).getByText("$100.00")).toBeInTheDocument();
    expect(within(totals as HTMLElement).getAllByText("$105.00")).toHaveLength(1);
    expect(screen.getAllByText("$105.00").length).toBeGreaterThanOrEqual(2);
  });

  it("sends selected optional row IDs when the recipient pays", async () => {
    const user = userEvent.setup();
    vi.mocked(publicInvoicesApi.pay).mockImplementation(() => new Promise(() => {}));
    const optionalId = "22222222-2222-4222-8222-222222222222";
    renderView(
      invoice({
        line_items: [
          invoice().line_items[0],
          {
            id: optionalId,
            name: "Downspout flush",
            description: null,
            quantity: 1,
            unit_price: 40,
            discount: 0,
            total: 40,
            is_optional: true,
            is_selected: true,
          },
        ],
        subtotal: 525,
        total: 525,
        balance_due: 525,
      }),
    );

    const checkbox = screen.getByRole("checkbox", { name: "Include Downspout flush" });
    await user.click(checkbox);
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: /pay now/i }));

    await waitFor(() =>
      expect(publicInvoicesApi.pay).toHaveBeenCalledWith(invoice().token, [optionalId]),
    );
  });

  it("exposes a table a screen reader can navigate", () => {
    renderView(invoice());

    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Item" })).toBeInTheDocument();
    expect(table).toHaveAccessibleName(/line items for invoice INV-000001/i);
    expect(screen.getByRole("heading", { level: 1, name: /maxteriors/i })).toBeInTheDocument();
  });
});
