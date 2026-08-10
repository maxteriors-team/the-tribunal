import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { PublicProposal } from "@/types/proposal";

import { PlainQuoteView } from "./plain-quote-view";

function proposal(overrides: Partial<PublicProposal> = {}): PublicProposal {
  return {
    token: "public-token",
    number: "QUO-1001",
    title: "Roof replacement",
    status: "sent",
    currency: "USD",
    subtotal: 9000,
    tax_amount: 0,
    discount_amount: 0,
    total: 9000,
    financing: {
      provider: "Wisetack",
      terms: [12, 24],
      default_term: 24,
      apr: 0,
      monthly_payment: 375,
      monthly_by_term: { "12": 750, "24": 375 },
      headline: "Flexible payment options",
      body: "Estimated monthly payments for this roof project.",
      points: [],
      disclaimer:
        "Payment figures are estimates, not offers, and remain subject to approval.",
    },
    is_expired: false,
    is_decided: false,
    deposit_paid: false,
    line_items: [
      {
        name: "Roof replacement",
        quantity: 1,
        unit_price: 9000,
        discount: 0,
        total: 9000,
      },
    ],
    branding: {
      business_name: "Maxteriors",
      brand_color: "#d4af5a",
      accent_color: "#d4af5a",
    },
    ...overrides,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderQuote(overrides: Partial<PublicProposal> = {}) {
  render(
    <PlainQuoteView
      data={proposal(overrides)}
      justApproved={false}
      justDeclined={false}
      busy={false}
      actionError={false}
      onApprove={vi.fn()}
      onDecline={vi.fn()}
    />,
    { wrapper },
  );
}

describe("plain quote financing", () => {
  it("shows the server estimate and disclaimer beside the core quote total", () => {
    renderQuote();

    expect(screen.getAllByText("$9,000.00").length).toBeGreaterThan(0);
    const estimate = screen.getByRole("complementary", {
      name: /estimated financing payments/i,
    });
    expect(estimate).toHaveTextContent("$375/month");
    expect(estimate).toHaveTextContent(
      "Payment figures are estimates, not offers, and remain subject to approval.",
    );
    expect(estimate).toHaveTextContent("Wisetack");
  });

  it("shows no financing language when the quote does not qualify", () => {
    renderQuote({ financing: null, total: 400, subtotal: 400 });

    expect(
      screen.queryByRole("complementary", {
        name: /estimated financing payments/i,
      }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/\/month/)).not.toBeInTheDocument();
  });
});

describe("plain quote on-site payment", () => {
  it("labels a 100% deposit as full payment", () => {
    renderQuote({
      deposit_percentage: 100,
      deposit_amount: 9000,
      deposit_required: true,
    });

    expect(screen.getByText("Payment Due Today")).toBeVisible();
    expect(screen.getByText("Full one-time total")).toBeVisible();
    expect(screen.getByRole("button", { name: "Pay Now" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Approve & Pay Now/ })).toBeVisible();
  });
});
